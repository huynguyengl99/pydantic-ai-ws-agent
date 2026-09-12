from collections.abc import Sequence
from typing import Any

from ag_ui.core import EventType, RunAgentInput, StateSnapshotEvent
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from app import db
from app.assistant.agent import AgentDeps, agent
from app.assistant.store import SqliteConversationStore
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


class TaskletTopic(PydanticAIAgUiTopic):
    """Tasklet over AG-UI, one thread per conversation."""

    agent = agent
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

    async def on_subscribe(self) -> None:
        # State first: a client joining mid-run applies the replayed events on top
        # of a task list that is already current.
        await self.send_run_event(await self.task_state(), seq=None)
        await super().on_subscribe()

    async def save_history(self, messages: Sequence[ModelMessage]) -> None:
        await super().save_history(messages)
        await db.set_title(self.thread_id, derive_title(messages))

    async def on_run_complete(self, result: Any) -> None:
        await super().on_run_complete(result)
        # Tools mutate the task list, so publish it with the run rather than
        # making the client refetch.
        await self.emit(await self.task_state())
