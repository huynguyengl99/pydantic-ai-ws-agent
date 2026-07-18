from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Literal

from chanx.messages.base import BaseMessage
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelMessagesTypeAdapter,
    RunContext,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_core import to_jsonable_python

from app import db
from app.assistant.agent import AgentDeps, AgentOutput, TextAnswer
from app.assistant.messages import (
    AgentErrorMessage,
    ApprovalRequestMessage,
    ApprovalRequestPayload,
    ErrorPayload,
    StreamEndMessage,
    StreamEndPayload,
    StreamStartMessage,
    StreamStartPayload,
    SuggestionsMessage,
    SuggestionsPayload,
    TasksUpdatedMessage,
    TasksUpdatedPayload,
    TextDeltaMessage,
    TextDeltaPayload,
    TextTranscriptItem,
    ToolCallMessage,
    ToolCallPayload,
    ToolDecision,
    ToolResultMessage,
    ToolResultPayload,
    ToolTranscriptItem,
    TranscriptItem,
    UsageInfo,
    UserMessage,
    UserMessagePayload,
)

SendFn = Callable[[BaseMessage], Awaitable[None]]

# pydantic-ai's default name for the structured-output tool that carries the
# final TextAnswer — its calls replay as assistant text, not tool cards.
FINAL_RESULT_TOOL = "final_result"


def _derive_title(user_prompt: str | None) -> str | None:
    if not user_prompt or not user_prompt.strip():
        return None
    line = user_prompt.strip().splitlines()[0]
    return line if len(line) <= 60 else line[:59] + "…"


def _tool_transcript_item(
    call: ToolCallPart, ret: ToolReturnPart | RetryPromptPart | None
) -> ToolTranscriptItem:
    match ret:
        case ToolReturnPart(outcome="denied"):
            status: Literal["done", "denied", "awaiting"] = "denied"
        case None:
            status = "awaiting"
        case _:
            status = "done"
    return ToolTranscriptItem(
        kind="tool",
        tool_call_id=call.tool_call_id,
        tool_name=call.tool_name,
        args=call.args_as_dict(),
        status=status,
        result=to_jsonable_python(ret.content)
        if isinstance(ret, ToolReturnPart)
        else None,
    )


def build_transcript(messages: list[ModelMessage]) -> list[TranscriptItem]:
    # Pass 1: index tool returns (and validation retries, so retried calls
    # don't render as "awaiting") by tool_call_id.
    returns: dict[str, ToolReturnPart | RetryPromptPart] = {}
    for message in messages:
        match message:
            case ModelRequest(parts=parts):
                for part in parts:
                    match part:
                        case ToolReturnPart() | RetryPromptPart():
                            returns[part.tool_call_id] = part
                        case _:
                            pass
            case _:
                pass

    # Pass 2: emit items in message order, preserving text/tool interleaving.
    items: list[TranscriptItem] = []
    for message in messages:
        match message:
            case ModelRequest(parts=request_parts):
                for part in request_parts:
                    match part:
                        case UserPromptPart(content=str() as content):
                            items.append(
                                TextTranscriptItem(
                                    kind="text", role="user", content=content
                                )
                            )
                        case _:
                            pass
            case ModelResponse(parts=response_parts):
                text = ""
                for response_part in response_parts:
                    match response_part:
                        case TextPart(content=content):
                            text += content
                        case ToolCallPart() if (
                            response_part.tool_name == FINAL_RESULT_TOOL
                        ):
                            # The output tool carries the final answer.
                            answer = response_part.args_as_dict().get("content")
                            if isinstance(answer, str):
                                text += answer
                        case ToolCallPart():
                            if text:
                                items.append(
                                    TextTranscriptItem(
                                        kind="text", role="assistant", content=text
                                    )
                                )
                                text = ""
                            items.append(
                                _tool_transcript_item(
                                    response_part,
                                    returns.get(response_part.tool_call_id),
                                )
                            )
                        case _:
                            pass
                if text:
                    items.append(
                        TextTranscriptItem(kind="text", role="assistant", content=text)
                    )
    return items


def approval_request_message(requests: DeferredToolRequests) -> ApprovalRequestMessage:
    return ApprovalRequestMessage(
        payload=ApprovalRequestPayload(
            calls=[
                ToolCallPayload(
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    args=part.args_as_dict(),
                )
                for part in requests.approvals
            ]
        )
    )


# Pending approval requests per conversation. Keyed by conversation id (not per
# connection) so an approval can arrive on a different socket than the one that
# started the run. Use a database table if this must survive restarts.
PENDING_APPROVALS: dict[str, DeferredToolRequests] = {}


class AgentHarness:
    """Runs an agent turn and translates pydantic-ai events into typed WS messages."""

    def __init__(
        self,
        agent: Agent[AgentDeps, AgentOutput],
        conversation_id: str,
        send: SendFn,
    ) -> None:
        self.agent = agent
        self.conversation_id = conversation_id
        self.send = send

    async def load_history(self) -> list[ModelMessage]:
        raw = await db.load_history(self.conversation_id)
        return ModelMessagesTypeAdapter.validate_json(raw) if raw else []

    async def run(
        self,
        user_prompt: str | None,
        deferred_tool_results: DeferredToolResults | None = None,
    ) -> None:
        history = await self.load_history()
        title = _derive_title(user_prompt) if not history else None
        # Chips always describe the latest answer: drop the previous ones as soon
        # as a new run starts, so a mid-run reconnect can't replay stale chips.
        await db.save_suggestions(self.conversation_id, [])
        if user_prompt is not None:
            # Echo the prompt to the whole group — every tab (the sender
            # included) renders the user bubble from this broadcast.
            await self.send(UserMessage(payload=UserMessagePayload(text=user_prompt)))
        await self.send(
            StreamStartMessage(
                payload=StreamStartPayload(conversation_id=self.conversation_id)
            )
        )

        tools_ran = False

        async def forward_tool_events(
            _ctx: RunContext[AgentDeps], events: AsyncIterable[AgentStreamEvent]
        ) -> None:
            nonlocal tools_ran
            async for event in events:
                match event:
                    case FunctionToolCallEvent(part=part):
                        await self.send(
                            ToolCallMessage(
                                payload=ToolCallPayload(
                                    tool_call_id=part.tool_call_id,
                                    tool_name=part.tool_name,
                                    args=part.args_as_dict(),
                                )
                            )
                        )
                    case FunctionToolResultEvent(part=part):
                        tools_ran = True
                        await self.send(
                            ToolResultMessage(
                                payload=ToolResultPayload(
                                    tool_call_id=part.tool_call_id,
                                    content=to_jsonable_python(part.content),
                                )
                            )
                        )
                    case _:
                        pass

        output: AgentOutput | None = None
        sent_text = ""
        async with self.agent.run_stream(
            user_prompt,
            message_history=history,
            deferred_tool_results=deferred_tool_results,
            deps=AgentDeps(conversation_id=self.conversation_id),
            event_stream_handler=forward_tool_events,
        ) as stream:
            # Partial validation yields growing TextAnswer snapshots; diffing
            # successive `content` values recovers the text deltas to stream.
            async for partial in stream.stream_output(debounce_by=None):
                match partial:
                    case TextAnswer(content=content) if (
                        content and content != sent_text
                    ):
                        delta = (
                            content.removeprefix(sent_text)
                            if content.startswith(sent_text)
                            else content
                        )
                        await self.send(
                            TextDeltaMessage(payload=TextDeltaPayload(delta=delta))
                        )
                        sent_text = content
                    case _:
                        pass
                output = partial
            usage = stream.usage
            await db.save_history(
                self.conversation_id, stream.all_messages_json().decode(), title
            )

        assert output is not None

        if tools_ran:
            await self.send(
                TasksUpdatedMessage(
                    payload=TasksUpdatedPayload(
                        tasks=await db.list_tasks(self.conversation_id)
                    )
                )
            )

        match output:
            case DeferredToolRequests() as requests:
                # run_stream stops forwarding events once the final result (the
                # deferred requests) is found, so announce the paused calls here
                # — same ids and wire order the live-execution path produces.
                for part in requests.approvals:
                    await self.send(
                        ToolCallMessage(
                            payload=ToolCallPayload(
                                tool_call_id=part.tool_call_id,
                                tool_name=part.tool_name,
                                args=part.args_as_dict(),
                            )
                        )
                    )
                PENDING_APPROVALS[self.conversation_id] = requests
                await self.send(approval_request_message(requests))
            case TextAnswer(content=content, follow_ups=follow_ups):
                await self.send(
                    StreamEndMessage(
                        payload=StreamEndPayload(
                            text=content,
                            usage=UsageInfo(
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                            ),
                        )
                    )
                )
                if follow_ups:
                    follow_ups = follow_ups[:3]
                    await db.save_suggestions(self.conversation_id, follow_ups)
                    await self.send(
                        SuggestionsMessage(
                            payload=SuggestionsPayload(follow_ups=follow_ups)
                        )
                    )

    async def resolve(self, decisions: list[ToolDecision]) -> None:
        if self.conversation_id not in PENDING_APPROVALS:
            await self.send(
                AgentErrorMessage(
                    payload=ErrorPayload(detail="No tool calls are awaiting approval")
                )
            )
            return

        approvals: dict[str, bool | ToolApproved | ToolDenied] = {
            decision.tool_call_id: (
                ToolApproved(override_args=decision.override_args)
                if decision.approved
                else ToolDenied(message=decision.reason or "Denied by the user")
            )
            for decision in decisions
        }

        del PENDING_APPROVALS[self.conversation_id]
        await self.run(None, DeferredToolResults(approvals=approvals))
