import asyncio
import uuid
from collections.abc import Coroutine
from typing import ClassVar
from urllib.parse import parse_qs

from chanx.core.decorators import channel, ws_handler
from chanx.messages.base import BaseMessage

from app import db
from app.assistant.agent import agent
from app.assistant.harness import (
    PENDING_APPROVALS,
    AgentHarness,
    approval_request_message,
    build_transcript,
)
from app.assistant.messages import (
    BROADCAST_MESSAGES,
    AgentErrorMessage,
    AgentServerMessage,
    ChatMessage,
    ErrorPayload,
    HistoryMessage,
    HistoryPayload,
    SuggestionsMessage,
    SuggestionsPayload,
    TasksUpdatedMessage,
    TasksUpdatedPayload,
    ToolDecisionMessage,
)
from app.ws import BaseConsumer

# One agent run at a time per conversation, across all connections.
RUNNING: dict[str, asyncio.Task[None]] = {}


def conversation_group(conversation_id: str) -> str:
    return f"conversation.{conversation_id}"


@channel(
    name="agent",
    description="Pydantic AI task assistant over a typed WebSocket",
    tags=["agent", "ai"],
)
class AgentConsumer(BaseConsumer):
    # Events broadcast to the conversation group are forwarded to the client
    # verbatim — chanx generates the event handlers (and AsyncAPI docs) for us.
    passthrough_events: ClassVar[list[type[BaseMessage]]] = BROADCAST_MESSAGES

    harness: AgentHarness
    conversation_id: str

    async def post_authentication(self) -> None:
        query = parse_qs(self.scope.get("query_string", b"").decode())
        self.conversation_id = query.get("conversation", [str(uuid.uuid4())])[0]

        group = conversation_group(self.conversation_id)
        await self.channel_layer.group_add(group, self.channel_name)
        if group not in self.groups:
            self.groups.append(group)

        self.harness = AgentHarness(agent, self.conversation_id, self._broadcast)

        # Per-connection snapshot; live updates arrive via the group.
        history = await self.harness.load_history()
        await self.send_message(
            HistoryMessage(
                payload=HistoryPayload(
                    conversation_id=self.conversation_id,
                    items=build_transcript(history),
                )
            )
        )
        await self.send_message(
            TasksUpdatedMessage(
                payload=TasksUpdatedPayload(
                    tasks=await db.list_tasks(self.conversation_id)
                )
            )
        )

        # Replay the latest answer's follow-up chips (cleared at each run start,
        # so these are never stale).
        follow_ups = await db.load_suggestions(self.conversation_id)
        if follow_ups:
            await self.send_message(
                SuggestionsMessage(payload=SuggestionsPayload(follow_ups=follow_ups))
            )

        # A refresh must not orphan a pending approval: re-send the request so
        # the new connection gets a working approval card.
        pending = PENDING_APPROVALS.get(self.conversation_id)
        if pending is not None:
            await self.send_message(approval_request_message(pending))

    async def _broadcast(self, message: BaseMessage) -> None:
        await self.broadcast_event(
            message, groups=conversation_group(self.conversation_id)
        )

    def _spawn_run(self, coro: Coroutine[None, None, None]) -> None:
        """Run an agent turn in the background so the handler returns immediately.

        The task outlives this connection: a client that refreshes mid-run keeps
        receiving events through the conversation group.
        """
        conversation_id = self.conversation_id

        async def guarded() -> None:
            try:
                await coro
            except Exception as exc:  # noqa: BLE001 - surface any run failure to the client
                await self._broadcast(
                    AgentErrorMessage(payload=ErrorPayload(detail=str(exc)))
                )
            finally:
                RUNNING.pop(conversation_id, None)

        RUNNING[conversation_id] = asyncio.create_task(guarded())

    @ws_handler(
        summary="Send a prompt to the agent",
        description=(
            "Starts one agent turn in the background. Events stream to every "
            "connection in the conversation group: text deltas, tool activity, "
            "then stream_end — or approval_request when a destructive tool "
            "needs sign-off."
        ),
        output_type=AgentServerMessage,
    )
    async def handle_chat(self, message: ChatMessage) -> None:
        if self.conversation_id in RUNNING:
            await self.send_message(
                AgentErrorMessage(
                    payload=ErrorPayload(detail="A run is already in progress")
                )
            )
            return
        self._spawn_run(self.harness.run(message.payload.text))

    @ws_handler(
        summary="Approve or deny pending tool calls",
        description=(
            "Resolves a previous approval_request and resumes the paused run with "
            "pydantic-ai deferred tool results."
        ),
        output_type=AgentServerMessage,
    )
    async def handle_tool_decision(self, message: ToolDecisionMessage) -> None:
        if self.conversation_id in RUNNING:
            await self.send_message(
                AgentErrorMessage(
                    payload=ErrorPayload(detail="A run is already in progress")
                )
            )
            return
        self._spawn_run(self.harness.resolve(message.payload.decisions))
