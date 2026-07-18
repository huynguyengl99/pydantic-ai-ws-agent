import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

import pytest
from chanx.fast_channels.testing import WebsocketCommunicator
from chanx.messages.base import BaseMessage
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from app import db
from app.assistant import consumer as consumer_mod
from app.assistant.agent import build_agent
from app.assistant.consumer import AgentConsumer
from app.assistant.messages import (
    AgentErrorMessage,
    ApprovalRequestMessage,
    ChatMessage,
    ChatPayload,
    HistoryMessage,
    NotificationMessage,
    StreamEndMessage,
    SuggestionsMessage,
    TasksUpdatedMessage,
    TextDeltaMessage,
    TextTranscriptItem,
    ToolCallMessage,
    ToolDecision,
    ToolDecisionMessage,
    ToolDecisionPayload,
    ToolResultMessage,
    ToolTranscriptItem,
    UserMessage,
)
from app.main import app

StreamFlow = Callable[..., AsyncIterator[str | dict[int, DeltaToolCall]]]
UseFlow = Callable[[StreamFlow], None]

SUGGESTIONS = ["List my tasks", "Mark it done", "Add another task"]

M = TypeVar("M", bound=BaseMessage)


def find(messages: list[BaseMessage], kind: type[M]) -> M:
    return next(m for m in messages if isinstance(m, kind))


def final_answer_args(content: str, follow_ups: list[str] | None = None) -> str:
    """JSON args for the structured-output (TextAnswer) tool call."""
    return json.dumps({"content": content, "follow_ups": follow_ups or []})


async def add_task_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    last_parts = messages[-1].parts
    if any(isinstance(p, ToolReturnPart) for p in last_parts):
        args = final_answer_args('Added "Buy milk" to your list.', SUGGESTIONS)
        split = args.index("to your list")  # split mid-content: 2+ text deltas
        yield {0: DeltaToolCall(name=info.output_tools[0].name, json_args=args[:split])}
        yield {0: DeltaToolCall(json_args=args[split:])}
    else:
        yield {0: DeltaToolCall(name="add_task", json_args='{"title": "Buy milk"}')}


async def delete_task_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    last_parts = messages[-1].parts
    tool_return = next((p for p in last_parts if isinstance(p, ToolReturnPart)), None)
    if tool_return is not None:
        yield {
            0: DeltaToolCall(
                name=info.output_tools[0].name,
                json_args=final_answer_args(f"Result: {tool_return.content}"),
            )
        }
    else:
        yield {0: DeltaToolCall(name="delete_task", json_args='{"task_id": 1}')}


async def slow_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    args = final_answer_args("Working done.")
    split = args.index("done")
    yield {0: DeltaToolCall(name=info.output_tools[0].name, json_args=args[:split])}
    await asyncio.sleep(0.5)
    yield {0: DeltaToolCall(json_args=args[split:])}


async def reminder_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    last_parts = messages[-1].parts
    if any(isinstance(p, ToolReturnPart) for p in last_parts):
        yield {
            0: DeltaToolCall(
                name=info.output_tools[0].name,
                json_args=final_answer_args("Reminder set."),
            )
        }
    else:
        yield {
            0: DeltaToolCall(
                name="schedule_reminder",
                json_args='{"message": "Stretch!", "delay_seconds": 0}',
            )
        }


@pytest.fixture
def use_flow(monkeypatch: pytest.MonkeyPatch) -> UseFlow:
    def _use(flow: StreamFlow) -> None:
        monkeypatch.setattr(
            consumer_mod, "agent", build_agent(FunctionModel(stream_function=flow))
        )

    return _use


def communicator(conversation: str) -> WebsocketCommunicator:
    return WebsocketCommunicator(
        app, f"/ws/agent?conversation={conversation}", consumer=AgentConsumer
    )


@asynccontextmanager
async def connect(
    conversation: str, *, expect_approval: bool = False
) -> AsyncGenerator[WebsocketCommunicator]:
    """Connected communicator with the on-connect snapshot already consumed."""
    async with communicator(conversation) as comm:
        # A pending approval is replayed to every new connection, after the
        # history + task snapshot.
        stop = "approval_request" if expect_approval else "tasks_updated"
        messages = await comm.receive_all_messages(stop_action=stop)
        assert [m.action for m in messages][:2] == ["history", "tasks_updated"]
        yield comm


async def test_chat_streams_tool_call_and_text(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-add") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        replies = await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    actions = [m.action for m in replies]
    # the user's prompt is echoed to the whole group before the run starts
    assert actions[:2] == ["user_message", "stream_start"]
    assert find(replies, UserMessage).payload.text == "Add buy milk"
    assert "tool_call" in actions
    assert "tool_result" in actions
    assert "text_delta" in actions
    assert actions[-1] == "stream_end"
    assert actions.index("tool_call") < actions.index("tool_result")

    tool_call = find(replies, ToolCallMessage)
    assert tool_call.payload.tool_name == "add_task"
    assert tool_call.payload.args == {"title": "Buy milk"}

    deltas = [m.payload.delta for m in replies if isinstance(m, TextDeltaMessage)]
    assert len(deltas) >= 2  # streamed in chunks, not one blob

    assert (
        find(replies, StreamEndMessage).payload.text == 'Added "Buy milk" to your list.'
    )
    assert find(replies, TasksUpdatedMessage).payload.tasks == [
        db.TaskItem(id=1, title="Buy milk", done=False)
    ]
    assert await db.load_history("conv-add") is not None


async def test_destructive_tool_requires_approval_then_runs(use_flow: UseFlow) -> None:
    use_flow(delete_task_flow)
    await db.add_task("conv-delete", "Ship the blog post")

    async with connect("conv-delete") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Delete task 1")))
        replies = await comm.receive_all_messages(
            stop_action="approval_request", timeout=5
        )

        # the tool_call event still fires for the deferred call, then the run pauses
        assert [m.action for m in replies] == [
            "user_message",
            "stream_start",
            "tool_call",
            "approval_request",
        ]
        call = find(replies, ApprovalRequestMessage).payload.calls[0]
        assert call.tool_name == "delete_task"
        assert call.args == {"task_id": 1}
        assert (await db.list_tasks("conv-delete")) != []  # nothing deleted yet

        await comm.send_message(
            ToolDecisionMessage(
                payload=ToolDecisionPayload(
                    decisions=[
                        ToolDecision(tool_call_id=call.tool_call_id, approved=True)
                    ]
                )
            )
        )
        replies = await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    actions = [m.action for m in replies]
    assert "tool_result" in actions
    assert actions[-1] == "stream_end"
    assert await db.list_tasks("conv-delete") == []  # task actually deleted
    assert "Task 1 deleted" in find(replies, StreamEndMessage).payload.text


async def test_denied_tool_does_not_run(use_flow: UseFlow) -> None:
    use_flow(delete_task_flow)
    await db.add_task("conv-deny", "Precious task")

    async with connect("conv-deny") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Delete task 1")))
        replies = await comm.receive_all_messages(
            stop_action="approval_request", timeout=5
        )
        call = find(replies, ApprovalRequestMessage).payload.calls[0]

        await comm.send_message(
            ToolDecisionMessage(
                payload=ToolDecisionPayload(
                    decisions=[
                        ToolDecision(
                            tool_call_id=call.tool_call_id,
                            approved=False,
                            reason="Keep that task",
                        )
                    ]
                )
            )
        )
        replies = await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    assert replies[-1].action == "stream_end"
    assert len(await db.list_tasks("conv-deny")) == 1  # still there


async def test_approval_survives_reconnect(use_flow: UseFlow) -> None:
    use_flow(delete_task_flow)
    await db.add_task("conv-reconnect", "Reconnect me")

    async with connect("conv-reconnect") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Delete task 1")))
        replies = await comm.receive_all_messages(
            stop_action="approval_request", timeout=5
        )
        call = find(replies, ApprovalRequestMessage).payload.calls[0]

    # approve from a brand-new connection (which receives the replayed request)
    async with connect("conv-reconnect", expect_approval=True) as comm:
        await comm.send_message(
            ToolDecisionMessage(
                payload=ToolDecisionPayload(
                    decisions=[
                        ToolDecision(tool_call_id=call.tool_call_id, approved=True)
                    ]
                )
            )
        )
        replies = await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    assert replies[-1].action == "stream_end"
    assert await db.list_tasks("conv-reconnect") == []


async def test_concurrent_run_rejected(use_flow: UseFlow) -> None:
    use_flow(slow_flow)
    async with connect("conv-busy") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="First")))
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Second")))
        replies = await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    errors = [m for m in replies if isinstance(m, AgentErrorMessage)]
    assert len(errors) == 1
    assert "already in progress" in errors[0].payload.detail


async def test_two_tabs_both_receive_the_stream(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-tabs") as first, connect("conv-tabs") as second:
        await first.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        first_replies = await first.receive_all_messages(
            stop_action="stream_end", timeout=5
        )
        second_replies = await second.receive_all_messages(
            stop_action="stream_end", timeout=5
        )

    # same broadcast feed on both sockets
    assert [m.action for m in first_replies] == [m.action for m in second_replies]
    assert any(isinstance(m, TextDeltaMessage) for m in second_replies)


async def test_reminder_tool_notifies_back(use_flow: UseFlow) -> None:
    use_flow(reminder_flow)
    async with connect("conv-reminder") as comm:
        await comm.send_message(
            ChatMessage(payload=ChatPayload(text="Remind me to stretch"))
        )
        replies = await comm.receive_all_messages(stop_action="stream_end", timeout=5)

        # the scheduled job broadcasts into the group (with delay 0 it may land
        # while the run is still streaming)
        if not any(isinstance(m, NotificationMessage) for m in replies):
            replies += await comm.receive_all_messages(
                stop_action="notification", timeout=5
            )

    content = find(replies, ToolResultMessage).payload.content
    assert isinstance(content, str)
    assert "Reminder scheduled" in content

    notification = find(replies, NotificationMessage)
    assert notification.payload.title == "Reminder"
    assert notification.payload.body == "Stretch!"


async def test_notification_endpoint_broadcasts(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-notify") as comm:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/conversations/conv-notify/notify",
                json={"title": "Reminder", "body": "Stand-up in 5 minutes"},
            )
        assert response.json() == {"delivered": True}

        replies = await comm.receive_all_messages(stop_action="notification", timeout=5)

    notification = find(replies, NotificationMessage)
    assert notification.payload.title == "Reminder"
    assert notification.payload.body == "Stand-up in 5 minutes"


async def test_history_replayed_on_reconnect(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-history") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    async with communicator("conv-history") as comm:
        messages = await comm.receive_all_messages(stop_action="history")

    items = find(messages, HistoryMessage).payload.items
    assert TextTranscriptItem(kind="text", role="user", content="Add buy milk") in items
    last = items[-1]
    assert isinstance(last, TextTranscriptItem)
    assert last.role == "assistant"


async def test_tasks_scoped_per_conversation(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-scope-a") as comm_a:
        await comm_a.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        replies = await comm_a.receive_all_messages(stop_action="stream_end", timeout=5)
    assert find(replies, TasksUpdatedMessage).payload.tasks != []

    # A different conversation gets an empty snapshot.
    async with communicator("conv-scope-b") as comm_b:
        messages = await comm_b.receive_all_messages(stop_action="tasks_updated")
    assert find(messages, TasksUpdatedMessage).payload.tasks == []

    assert len(await db.list_tasks("conv-scope-a")) == 1
    assert await db.list_tasks("conv-scope-b") == []


async def test_history_replays_tool_calls(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-tool-replay") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    async with communicator("conv-tool-replay") as comm:
        messages = await comm.receive_all_messages(stop_action="history")

    items = find(messages, HistoryMessage).payload.items
    tool = next(i for i in items if isinstance(i, ToolTranscriptItem))
    assert tool.tool_name == "add_task"
    assert tool.args == {"title": "Buy milk"}
    assert tool.status == "done"
    assert tool.result is not None


async def test_denied_tool_replays_as_denied(use_flow: UseFlow) -> None:
    use_flow(delete_task_flow)
    await db.add_task("conv-denied-replay", "Precious task")

    async with connect("conv-denied-replay") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Delete task 1")))
        replies = await comm.receive_all_messages(
            stop_action="approval_request", timeout=5
        )
        call = find(replies, ApprovalRequestMessage).payload.calls[0]
        await comm.send_message(
            ToolDecisionMessage(
                payload=ToolDecisionPayload(
                    decisions=[
                        ToolDecision(tool_call_id=call.tool_call_id, approved=False)
                    ]
                )
            )
        )
        await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    async with communicator("conv-denied-replay") as comm:
        messages = await comm.receive_all_messages(stop_action="history")

    items = find(messages, HistoryMessage).payload.items
    tool = next(i for i in items if isinstance(i, ToolTranscriptItem))
    assert tool.tool_name == "delete_task"
    assert tool.status == "denied"


async def test_pending_approval_replays_as_awaiting(use_flow: UseFlow) -> None:
    use_flow(delete_task_flow)
    await db.add_task("conv-awaiting", "Task to keep waiting")

    async with connect("conv-awaiting") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Delete task 1")))
        # ends with approval_request; no decision is made
        await comm.receive_all_messages(stop_action="approval_request", timeout=5)

    async with communicator("conv-awaiting") as comm:
        messages = await comm.receive_all_messages(stop_action="approval_request")

    items = find(messages, HistoryMessage).payload.items
    tool = next(i for i in items if isinstance(i, ToolTranscriptItem))
    assert tool.status == "awaiting"
    assert tool.result is None
    approval = find(messages, ApprovalRequestMessage)
    assert approval.payload.calls[0].tool_name == "delete_task"


async def test_suggestions_follow_stream_end(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-suggest") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        await comm.receive_all_messages(stop_action="stream_end", timeout=5)
        replies = await comm.receive_all_messages(stop_action="suggestions", timeout=5)

    assert find(replies, SuggestionsMessage).payload.follow_ups == SUGGESTIONS


async def test_suggestions_replayed_on_reconnect(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-suggest-replay") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        await comm.receive_all_messages(stop_action="suggestions", timeout=5)

    async with communicator("conv-suggest-replay") as comm:
        messages = await comm.receive_all_messages(stop_action="suggestions")

    assert [m.action for m in messages] == ["history", "tasks_updated", "suggestions"]
    assert find(messages, SuggestionsMessage).payload.follow_ups == SUGGESTIONS


async def test_title_set_from_first_prompt(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)
    async with connect("conv-title") as comm:
        await comm.send_message(ChatMessage(payload=ChatPayload(text="Add buy milk")))
        await comm.receive_all_messages(stop_action="stream_end", timeout=5)

    conversations = await db.list_conversations()
    conv = next(c for c in conversations if c.id == "conv-title")
    assert conv.title == "Add buy milk"


def test_asyncapi_contract_includes_all_actions() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    spec = client.get("/asyncapi.json").json()
    messages = spec["components"]["messages"]
    expected = {
        "chat_message",
        "tool_decision_message",
        "user_message",
        "stream_start_message",
        "text_delta_message",
        "tool_call_message",
        "tool_result_message",
        "approval_request_message",
        "stream_end_message",
        "suggestions_message",
        "history_message",
        "tasks_updated_message",
        "notification_message",
        "agent_error_message",
    }
    assert expected <= set(messages.keys())
