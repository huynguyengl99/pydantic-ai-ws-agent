from collections.abc import AsyncIterator, Sequence

from ag_ui.core import (
    Event,
    EventType,
    RunAgentInput,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    UserMessage,
)
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from app import db
from app.assistant.agent import AgentDeps, tasklet_agent
from app.assistant.store import SqliteConversationStore
from app.assistant.suggestions import follow_ups, suggestions_event
from app.ws_kits.pydantic_ai_ag_ui import PydanticAIAgUiTopic

TITLE_LIMIT = 60


def derive_title(messages: Sequence[ModelMessage]) -> str | None:
    """A conversation is named after its first prompt."""
    for message in messages:
        match message:
            case ModelRequest(parts=parts):
                for part in parts:
                    match part:
                        case UserPromptPart(content=str() as content) if (
                            content.strip()
                        ):
                            line = content.strip().splitlines()[0]
                            return (
                                line
                                if len(line) <= TITLE_LIMIT
                                else line[: TITLE_LIMIT - 1] + "…"
                            )
                        case _:
                            pass
            case _:
                pass
    return None


def prompt_echo(run_input: RunAgentInput) -> list[Event]:
    """The run's prompt as AG-UI events, so every tab renders it the same way.

    Nothing else puts the user's turn on the wire: the run carries only what the
    agent produces, which would leave a second tab showing an answer to a
    question it never saw. `messages` holds just the new turn, and is empty when
    a resumed approval re-enters the run.
    """
    events: list[Event] = []
    for message in run_input.messages:
        match message:
            case UserMessage(id=message_id, content=str() as text) if text:
                events += [
                    TextMessageStartEvent(
                        type=EventType.TEXT_MESSAGE_START,
                        message_id=message_id,
                        role="user",
                    ),
                    TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT,
                        message_id=message_id,
                        delta=text,
                    ),
                    TextMessageEndEvent(
                        type=EventType.TEXT_MESSAGE_END,
                        message_id=message_id,
                    ),
                ]
            case _:
                pass
    return events


def is_paused(event: Event) -> bool:
    """Whether a finished run stopped to ask for approval rather than completing."""
    outcome = getattr(event, "outcome", None)
    return getattr(outcome, "type", None) == "interrupt"


class TaskletTopic(PydanticAIAgUiTopic):
    """Tasklet over AG-UI, one thread per conversation."""

    agent = tasklet_agent
    conversation_store = SqliteConversationStore()
    channel_layer_alias = "agent"

    # Every tab on a conversation follows the same run, and one that connects
    # mid-run is replayed from RUN_STARTED.
    broadcast_run_events = True

    def agent_deps(self, run_input: RunAgentInput) -> AgentDeps:
        return AgentDeps(conversation_id=self.thread_id)

    async def task_state(self) -> StateSnapshotEvent:
        tasks = await db.list_tasks(self.thread_id)
        return StateSnapshotEvent(
            type=EventType.STATE_SNAPSHOT,
            snapshot={"tasks": [task.model_dump() for task in tasks]},
        )

    async def send_initial_state(self) -> None:
        # The kit sends the transcript; the task list and chips are ours. All of it
        # lands before the run in flight is replayed.
        await super().send_initial_state()
        await self.send_run_event(await self.task_state(), seq=None)
        await self.send_suggestions()

    async def send_suggestions(self) -> None:
        prompts = await db.load_suggestions(self.thread_id)
        if prompts:
            await self.send_run_event(suggestions_event(prompts), seq=None)

    async def save_history(self, messages: Sequence[ModelMessage]) -> None:
        await super().save_history(messages)
        await db.set_title(self.thread_id, derive_title(messages))

    async def run_events(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        # Chips describe the latest answer, so drop the previous ones now: a
        # reconnect mid-run must not replay stale ones.
        await db.save_suggestions(self.thread_id, [])

        async for event in super().run_events(run_input):
            # Tools mutate the task list, so the run carries the result rather than
            # leaving the client to refetch. Emitted on the failing path too: a run
            # that raises half way through has still changed the list.
            if event.type in (EventType.RUN_FINISHED, EventType.RUN_ERROR):
                yield await self.task_state()
            if event.type == EventType.RUN_FINISHED and not is_paused(event):
                prompts = await follow_ups(await self.load_history())
                if prompts:
                    await db.save_suggestions(self.thread_id, prompts)
                    yield suggestions_event(prompts)
            yield event
            # After RUN_STARTED, not before it: a run's events are numbered from
            # there, and a client resynchronises on it and drops what precedes.
            if event.type == EventType.RUN_STARTED:
                for echo in prompt_echo(run_input):
                    yield echo
