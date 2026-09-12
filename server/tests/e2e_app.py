"""The app with a scripted model, so the browser tests are deterministic.

Run by Playwright's `webServer`, never in production: a real model would make the
assertions depend on what it felt like saying.
"""

from collections.abc import AsyncIterator

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

from app.assistant.agent import build_agent
from app.assistant.topic import TaskletTopic
from app.main import app

__all__ = ["app"]


def last_prompt(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        match message:
            case ModelRequest(parts=parts):
                for part in parts:
                    match part:
                        case UserPromptPart(content=str() as content):
                            return content.lower()
                        case _:
                            pass
            case _:
                pass
    return ""


def is_continuation(messages: list[ModelMessage]) -> bool:
    """Whether this turn follows a tool call, rather than a fresh prompt.

    Checked against the current turn only: by the second prompt the history is
    full of earlier responses, so asking whether any tool ever ran is always yes.
    """
    for message in reversed(messages):
        if isinstance(message, ModelResponse):
            return True
        if isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart) for part in message.parts
        ):
            return False
    return False


def listed_task_ids(messages: list[ModelMessage]) -> list[int]:
    """Ids returned by the most recent `list_tasks`, newest call first."""
    for message in reversed(messages):
        match message:
            case ModelRequest(parts=parts):
                for part in parts:
                    if (
                        isinstance(part, ToolReturnPart)
                        and part.tool_name == "list_tasks"
                    ):
                        content = part.content
                        if isinstance(content, list):
                            return [
                                item["id"] if isinstance(item, dict) else item.id
                                for item in content
                            ]
            case _:
                pass
    return []


async def script(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    prompt = last_prompt(messages)

    if is_continuation(messages):
        # Ids come from the database, not from the script: the table counts up
        # across conversations, so the first task is rarely id 1.
        pending = listed_task_ids(messages)
        if "delete" in prompt and pending:
            yield {
                0: DeltaToolCall(
                    name="delete_task",
                    json_args=f'{{"task_id": {pending[0]}}}',
                    tool_call_id="del-1",
                )
            }
            return
        yield "All " if "delete" not in prompt else "Deleted "
        yield "done."
        return

    if "delete" in prompt:
        yield {0: DeltaToolCall(name="list_tasks", json_args="{}")}
    elif "remind" in prompt:
        yield {
            0: DeltaToolCall(
                name="schedule_reminder",
                json_args='{"message": "stretch", "delay_seconds": 0}',
            )
        }
    else:
        yield {0: DeltaToolCall(name="add_task", json_args='{"title": "Ship v2"}')}


TaskletTopic.agent = build_agent(FunctionModel(stream_function=script))
