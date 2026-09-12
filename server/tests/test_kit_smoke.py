"""The copied chanx-kit runs a Pydantic AI agent in this project."""

from collections.abc import AsyncIterator
from typing import Any, ClassVar

from chanx.core.decorators import channel
from chanx.core.topic import Topic
from chanx.fast_channels.testing import WebsocketCommunicator
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from fastapi import FastAPI
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

from app.layers import setup_layers
from app.ws_kits.ag_ui import AgUiEventMessage
from app.ws_kits.pydantic_ai_ag_ui import PydanticAIAgUiTopic

THREAD = "agui:thread:demo"

setup_layers()


async def stream_function(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    """First turn calls the approval-gated tool; once resolved, it answers."""
    if not any(isinstance(message, ModelResponse) for message in messages):
        yield {
            0: DeltaToolCall(
                name="delete_task", json_args='{"task": "7"}', tool_call_id="call-1"
            )
        }
    else:
        yield "Task 7 is gone."


agent = Agent(
    FunctionModel(stream_function=stream_function),
    output_type=[str, DeferredToolRequests],
)


@agent.tool_plain(requires_approval=True)
def delete_task(task: str) -> str:
    return f"deleted {task}"


class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent
    broadcast_run_events = True
    channel_layer_alias = "agent"


@channel(name="agent", description="AG-UI agent", tags=["agent"])
class KitAgentConsumer(AsyncJsonWebsocketConsumer[AgUiEventMessage]):
    channel_layer_alias = "agent"
    topics: ClassVar[list[type[Topic[Any]]]] = [TaskletTopic]


app = FastAPI()
app.router.add_websocket_route("/ws/agent", KitAgentConsumer.as_asgi())


def run_input(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "threadId": "demo",
        "runId": "run-1",
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "delete task 7"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    payload.update(overrides)
    return payload


def types_of(messages: list[dict[str, Any]]) -> list[str]:
    return [m["payload"]["type"] for m in messages]


async def test_the_kit_runs_an_agent_with_approvals() -> None:
    comm = WebsocketCommunicator(app, "/ws/agent", consumer=KitAgentConsumer)
    connected, _ = await comm.connect()
    assert connected
    await comm.subscribe(THREAD)

    await comm.send_json_to(
        {"version": 1, "topic": THREAD, "action": "ag_ui_run", "payload": run_input()}
    )
    paused = [await comm.receive_json_from(5) for _ in range(5)]

    assert types_of(paused) == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "RUN_FINISHED",
    ]
    # Broadcast mode stamps a per-run sequence for a late joiner to order by.
    assert [m["seq"] for m in paused] == [1, 2, 3, 4, 5]

    outcome = paused[-1]["payload"]["outcome"]
    assert outcome["type"] == "interrupt"

    # The conversation stayed on the server, so the resume carries no messages.
    await comm.send_json_to(
        {
            "version": 1,
            "topic": THREAD,
            "action": "ag_ui_run",
            "payload": run_input(
                runId="run-2",
                messages=[],
                resume=[
                    {
                        "interruptId": outcome["interrupts"][0]["id"],
                        "status": "resolved",
                        "payload": {"approved": True},
                    }
                ],
            ),
        }
    )
    resumed = [await comm.receive_json_from(5) for _ in range(6)]

    assert types_of(resumed) == [
        "RUN_STARTED",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert resumed[-1]["payload"]["outcome"]["type"] == "success"

    await comm.disconnect()
