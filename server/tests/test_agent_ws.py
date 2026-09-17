from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

import pytest
from chanx.fast_channels.testing import WebsocketCommunicator
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls

from app import db
from app.assistant.agent import build_agent
from app.assistant.consumer import AgentConsumer
from app.assistant.topic import TaskletTopic
from app.main import app

StreamFlow = Callable[..., AsyncIterator[str | dict[int, DeltaToolCall]]]
UseFlow = Callable[[StreamFlow], None]
T = TypeVar("T")

CONVERSATION = "conv-1"
THREAD = f"agui:thread:{CONVERSATION}"


def is_first_turn(messages: list[ModelMessage]) -> bool:
    return not any(isinstance(message, ModelResponse) for message in messages)


async def add_task_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    if is_first_turn(messages):
        yield {0: DeltaToolCall(name="add_task", json_args='{"title": "Write post"}')}
    else:
        yield "Added "
        yield "Write post."


async def delete_task_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    if is_first_turn(messages):
        yield {
            0: DeltaToolCall(
                name="delete_task", json_args='{"task_id": 1}', tool_call_id="call-1"
            )
        }
    else:
        yield "Done."


async def reminder_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    if is_first_turn(messages):
        yield {
            0: DeltaToolCall(
                name="schedule_reminder",
                json_args='{"message": "stretch", "delay_seconds": 0}',
            )
        }
    else:
        yield "Reminder set."


@pytest.fixture
def use_flow(monkeypatch: pytest.MonkeyPatch) -> UseFlow:
    from pydantic_ai.models.function import FunctionModel

    def _use(flow: StreamFlow) -> None:
        monkeypatch.setattr(
            TaskletTopic, "agent", build_agent(FunctionModel(stream_function=flow))
        )

    return _use


CHIPS = ["List my tasks", "Mark it done", "Add another task"]


@pytest.fixture(autouse=True)
def scripted_suggester(monkeypatch: pytest.MonkeyPatch) -> None:
    """TestModel returns an empty list for `list[str]`, so chips would never fire."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from app.assistant import suggestions

    def chips(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("final_result", {"prompts": CHIPS})])

    monkeypatch.setattr(
        suggestions, "suggester", suggestions.build_suggester(FunctionModel(chips))
    )


def communicator() -> WebsocketCommunicator:
    return WebsocketCommunicator(app, "/ws/agent", consumer=AgentConsumer)


def run_input(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "threadId": CONVERSATION,
        "runId": "run-1",
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "add a task"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    payload.update(overrides)
    return payload


async def subscribe(comm: WebsocketCommunicator) -> dict[str, Any]:
    """Subscribe and return the task-state snapshot sent on connect."""
    await comm.subscribe(THREAD)
    snapshot: dict[str, Any] = await comm.receive_json_from(5)
    return snapshot


async def send_run(comm: WebsocketCommunicator, **overrides: Any) -> None:
    await comm.send_json_to(
        {
            "version": 1,
            "topic": THREAD,
            "action": "ag_ui_run",
            "payload": run_input(**overrides),
        }
    )


async def drain_run(comm: WebsocketCommunicator) -> list[dict[str, Any]]:
    """Read one run's events, up to and including RUN_FINISHED."""
    events: list[dict[str, Any]] = []
    for _ in range(40):
        message = await comm.receive_json_from(5)
        events.append(message)
        if message["payload"]["type"] in ("RUN_FINISHED", "RUN_ERROR"):
            return events
    raise AssertionError(f"run did not finish; saw {types_of(events)}")


def types_of(events: list[dict[str, Any]]) -> list[str]:
    return [e["payload"]["type"] for e in events]


async def test_a_run_streams_its_tool_call_and_text(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm)
        events = await drain_run(comm)

    assert "TOOL_CALL_START" in types_of(events)
    assert "TEXT_MESSAGE_CONTENT" in types_of(events)
    assert types_of(events)[-1] == "RUN_FINISHED"
    assert await db.list_tasks(CONVERSATION)


async def test_the_task_list_is_published_with_the_run(use_flow: UseFlow) -> None:
    """Tools mutate tasks, so the run carries the new state rather than making
    the client refetch."""
    use_flow(add_task_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm)
        events = await drain_run(comm)

    snapshots = [e for e in events if e["payload"]["type"] == "STATE_SNAPSHOT"]
    assert snapshots, types_of(events)
    titles = [t["title"] for t in snapshots[-1]["payload"]["snapshot"]["tasks"]]
    assert titles == ["Write post"]


async def test_a_destructive_tool_pauses_for_approval(use_flow: UseFlow) -> None:
    use_flow(delete_task_flow)
    await db.add_task(CONVERSATION, "Delete me")

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm, messages=[{"id": "m1", "role": "user", "content": "del"}])
        events = await drain_run(comm)

        outcome = events[-1]["payload"]["outcome"]
        assert outcome["type"] == "interrupt"

        # Still there: the tool has not run.
        assert len(await db.list_tasks(CONVERSATION)) == 1

        await send_run(
            comm,
            runId="run-2",
            messages=[],
            resume=[
                {
                    "interruptId": outcome["interrupts"][0]["id"],
                    "status": "resolved",
                    "payload": {"approved": True},
                }
            ],
        )
        resumed = await drain_run(comm)

    assert "TOOL_CALL_RESULT" in types_of(resumed)
    assert await db.list_tasks(CONVERSATION) == []


async def test_a_denied_tool_does_not_run(use_flow: UseFlow) -> None:
    use_flow(delete_task_flow)
    await db.add_task(CONVERSATION, "Keep me")

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm, messages=[{"id": "m1", "role": "user", "content": "del"}])
        events = await drain_run(comm)
        outcome = events[-1]["payload"]["outcome"]

        await send_run(
            comm,
            runId="run-2",
            messages=[],
            resume=[
                {
                    "interruptId": outcome["interrupts"][0]["id"],
                    "status": "resolved",
                    "payload": {"approved": False, "reason": "Not that one"},
                }
            ],
        )
        await drain_run(comm)

    assert len(await db.list_tasks(CONVERSATION)) == 1


async def test_every_tab_follows_the_same_run(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)

    async with communicator() as first, communicator() as second:
        await subscribe(first)
        await subscribe(second)

        await send_run(first)
        from_first = await drain_run(first)
        from_second = await drain_run(second)

    assert types_of(from_first) == types_of(from_second)
    assert [e["seq"] for e in from_first] == [e["seq"] for e in from_second]


def user_echo(events: list[dict[str, Any]]) -> list[str]:
    """The prompts the run put on the wire, in order."""
    return [
        event["payload"]["delta"]
        for event in events
        if event["payload"]["type"] == "TEXT_MESSAGE_CONTENT"
        and event["payload"].get("messageId", "").startswith("m")
    ]


async def test_the_prompt_is_echoed_to_every_tab(use_flow: UseFlow) -> None:
    """Nothing else carries the user's turn, so a tab that did not send it would
    show an answer to a question it never saw."""
    use_flow(add_task_flow)

    async with communicator() as first, communicator() as second:
        await subscribe(first)
        await subscribe(second)

        await send_run(first)
        from_first = await drain_run(first)
        from_second = await drain_run(second)

    assert user_echo(from_first) == ["add a task"]
    assert user_echo(from_second) == ["add a task"]
    # A run is numbered from RUN_STARTED, and a client resynchronises on it, so
    # an echo sent before it is dropped as stale on every run but the first.
    types = types_of(from_first)
    assert types.index("RUN_STARTED") < types.index("TEXT_MESSAGE_START")


async def test_a_later_prompt_is_echoed_too(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm)
        await drain_run(comm)

        await send_run(
            comm,
            runId="run-2",
            messages=[{"id": "m2", "role": "user", "content": "and another"}],
        )
        second = await drain_run(comm)

    assert user_echo(second) == ["and another"]


async def test_the_conversation_is_kept_server_side(use_flow: UseFlow) -> None:
    """A second run sends no history, so continuing proves the server holds it."""
    use_flow(add_task_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm)
        await drain_run(comm)

    stored = await db.load_history(CONVERSATION)
    assert stored is not None and "Write post" in stored

    conversations = await db.list_conversations()
    assert conversations[0].title == "add a task"


async def test_a_reminder_notifies_the_conversation(use_flow: UseFlow) -> None:
    use_flow(reminder_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm, messages=[{"id": "m1", "role": "user", "content": "rem"}])
        # A zero-delay reminder can land inside the run as easily as after it.
        seen = await drain_run(comm)
        while not any(e["payload"]["type"] == "CUSTOM" for e in seen):
            seen.append(await comm.receive_json_from(5))

    notification = next(e for e in seen if e["payload"]["type"] == "CUSTOM")
    assert notification["payload"]["name"] == "notification"
    assert notification["payload"]["value"]["body"] == "stretch"


async def test_http_can_notify_a_conversation() -> None:
    async with communicator() as comm:
        await subscribe(comm)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/conversations/{CONVERSATION}/notify",
                json={"title": "Hi", "body": "from curl"},
            )
        assert response.json() == {"delivered": True}

        message = await comm.receive_json_from(5)

    assert message["payload"]["type"] == "CUSTOM"
    assert message["payload"]["value"]["body"] == "from curl"


async def failing_tool_flow(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    """Adds a task, then in a later turn calls a tool that raises.

    Two turns rather than two calls in one: tools within a response run
    concurrently, so the raising one could otherwise beat the write it is meant
    to happen after.
    """
    if is_first_turn(messages):
        yield {0: DeltaToolCall(name="add_task", json_args='{"title": "Survivor"}')}
    else:
        yield {0: DeltaToolCall(name="complete_task", json_args='{"task_id": 999}')}


async def test_a_failed_run_still_publishes_the_task_list(use_flow: UseFlow) -> None:
    """A run that raises half way through has still changed the list, and a
    stale panel is worse than a failed run."""
    use_flow(failing_tool_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm)
        events = await drain_run(comm)

    assert types_of(events)[-1] == "RUN_ERROR"
    snapshots = [e for e in events if e["payload"]["type"] == "STATE_SNAPSHOT"]
    assert snapshots, types_of(events)
    titles = [t["title"] for t in snapshots[-1]["payload"]["snapshot"]["tasks"]]
    assert titles == ["Survivor"]


async def test_a_reconnect_is_replayed_the_conversation(use_flow: UseFlow) -> None:
    """The paper trail: a new connection is told the conversation, as AG-UI
    messages, so a reload does not start from a blank page."""
    use_flow(add_task_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm)
        await drain_run(comm)

    async with communicator() as fresh:
        await fresh.subscribe(THREAD)
        first = await fresh.receive_json_from(5)

    assert first["payload"]["type"] == "MESSAGES_SNAPSHOT"
    messages = first["payload"]["messages"]
    assert [m["role"] for m in messages][:2] == ["user", "assistant"]
    assert any(m.get("content") == "add a task" for m in messages)
    assert any(m.get("toolCalls") for m in messages)


async def test_follow_up_chips_are_sent_and_replayed(use_flow: UseFlow) -> None:
    use_flow(add_task_flow)

    async with communicator() as comm:
        await subscribe(comm)
        await send_run(comm)
        events = await drain_run(comm)

    chips = [
        e
        for e in events
        if e["payload"]["type"] == "CUSTOM" and e["payload"]["name"] == "suggestions"
    ]
    assert chips, types_of(events)
    assert chips[-1]["payload"]["value"]["prompts"]

    # Persisted, so a reconnect gets them back without another model call.
    assert await db.load_suggestions(CONVERSATION)
