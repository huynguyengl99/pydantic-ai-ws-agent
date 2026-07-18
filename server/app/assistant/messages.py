from typing import Literal

from chanx.messages.base import BaseMessage
from pydantic import BaseModel, JsonValue

from app.db import TaskItem

# ---------- Client -> server ----------


class ChatPayload(BaseModel):
    text: str


class ChatMessage(BaseMessage):
    """User sends a prompt to the agent."""

    action: Literal["chat"] = "chat"
    payload: ChatPayload


class ToolDecision(BaseModel):
    tool_call_id: str
    approved: bool
    override_args: dict[str, JsonValue] | None = None
    reason: str | None = None


class ToolDecisionPayload(BaseModel):
    decisions: list[ToolDecision]


class ToolDecisionMessage(BaseMessage):
    """User approves or denies pending tool calls."""

    action: Literal["tool_decision"] = "tool_decision"
    payload: ToolDecisionPayload


# ---------- Server -> client ----------


class UserMessagePayload(BaseModel):
    text: str


class UserMessage(BaseMessage):
    """Echo of the user's prompt, broadcast so every connected tab shows it."""

    action: Literal["user_message"] = "user_message"
    payload: UserMessagePayload


class StreamStartPayload(BaseModel):
    conversation_id: str


class StreamStartMessage(BaseMessage):
    """The agent started processing a run."""

    action: Literal["stream_start"] = "stream_start"
    payload: StreamStartPayload


class TextDeltaPayload(BaseModel):
    delta: str


class TextDeltaMessage(BaseMessage):
    """A chunk of the agent's streaming text response."""

    action: Literal["text_delta"] = "text_delta"
    payload: TextDeltaPayload


class ToolCallPayload(BaseModel):
    tool_call_id: str
    tool_name: str
    args: dict[str, JsonValue]


class ToolCallMessage(BaseMessage):
    """The agent is calling a tool."""

    action: Literal["tool_call"] = "tool_call"
    payload: ToolCallPayload


class ToolResultPayload(BaseModel):
    tool_call_id: str
    content: JsonValue


class ToolResultMessage(BaseMessage):
    """A tool call finished and returned a result."""

    action: Literal["tool_result"] = "tool_result"
    payload: ToolResultPayload


class ApprovalRequestPayload(BaseModel):
    calls: list[ToolCallPayload]


class ApprovalRequestMessage(BaseMessage):
    """The agent needs user approval before running these tool calls."""

    action: Literal["approval_request"] = "approval_request"
    payload: ApprovalRequestPayload


class UsageInfo(BaseModel):
    input_tokens: int
    output_tokens: int


class StreamEndPayload(BaseModel):
    text: str
    usage: UsageInfo


class StreamEndMessage(BaseMessage):
    """The agent run finished with a final text response."""

    action: Literal["stream_end"] = "stream_end"
    payload: StreamEndPayload


class SuggestionsPayload(BaseModel):
    follow_ups: list[str]


class SuggestionsMessage(BaseMessage):
    """Suggested next prompts, generated after a completed run."""

    action: Literal["suggestions"] = "suggestions"
    payload: SuggestionsPayload


class TextTranscriptItem(BaseModel):
    # `kind` deliberately has no default: it must be `required` in the JSON
    # schema so the generated TS union can discriminate on it.
    kind: Literal["text"]
    role: Literal["user", "assistant"]
    content: str


class ToolTranscriptItem(BaseModel):
    kind: Literal["tool"]
    tool_call_id: str
    tool_name: str
    args: dict[str, JsonValue]
    status: Literal["done", "denied", "awaiting"]
    result: JsonValue | None = None


TranscriptItem = TextTranscriptItem | ToolTranscriptItem


class HistoryPayload(BaseModel):
    conversation_id: str
    items: list[TranscriptItem]


class HistoryMessage(BaseMessage):
    """Replay of the conversation transcript, sent on connect."""

    action: Literal["history"] = "history"
    payload: HistoryPayload


class TasksUpdatedPayload(BaseModel):
    tasks: list[TaskItem]


class TasksUpdatedMessage(BaseMessage):
    """The current state of the task list."""

    action: Literal["tasks_updated"] = "tasks_updated"
    payload: TasksUpdatedPayload


class NotificationPayload(BaseModel):
    title: str
    body: str


class NotificationMessage(BaseMessage):
    """An out-of-band notification pushed to the conversation, e.g. from an HTTP endpoint."""

    action: Literal["notification"] = "notification"
    payload: NotificationPayload


class ErrorPayload(BaseModel):
    detail: str


class AgentErrorMessage(BaseMessage):
    """Something went wrong while running the agent."""

    action: Literal["agent_error"] = "agent_error"
    payload: ErrorPayload


AgentServerMessage = (
    UserMessage
    | StreamStartMessage
    | TextDeltaMessage
    | ToolCallMessage
    | ToolResultMessage
    | ApprovalRequestMessage
    | StreamEndMessage
    | SuggestionsMessage
    | HistoryMessage
    | TasksUpdatedMessage
    | NotificationMessage
    | AgentErrorMessage
)

# Everything the harness or an external producer broadcasts to a conversation
# group — the consumer forwards these to the client verbatim.
BROADCAST_MESSAGES: list[type[BaseMessage]] = [
    UserMessage,
    StreamStartMessage,
    TextDeltaMessage,
    ToolCallMessage,
    ToolResultMessage,
    ApprovalRequestMessage,
    StreamEndMessage,
    SuggestionsMessage,
    TasksUpdatedMessage,
    NotificationMessage,
    AgentErrorMessage,
]
