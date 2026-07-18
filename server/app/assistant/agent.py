from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.models import Model

from app import db
from app.assistant import reminders
from app.config import settings

INSTRUCTIONS = """\
You are Tasklet, a friendly task management assistant.
You help the user manage their task list: list, add, complete, delete, and clear tasks.
You can also schedule reminder notifications with the schedule_reminder tool when the
user asks to be reminded about something.

When the user asks for a destructive operation (deleting or clearing tasks), call the
tool directly — do NOT ask for confirmation in chat. The system automatically pauses
destructive tool calls and asks the user for approval in the UI.
When a destructive tool call is denied, acknowledge it and do not retry.
Keep responses short and conversational. Refer to tasks by their id and title.

Also populate `follow_ups` with exactly 3 short prompts the user is likely to send
next — in the user's voice, in the answer's language, each concise enough to fit a
small chip (at most 8 words). Ground them in the actual task list: refer to real
tasks by id or title, suggest completing open tasks, adding an obvious missing step,
or a reminder when timing matters. At most ONE may be a destructive action
(delete / clear all). Never suggest anything you cannot actually do.
"""


class TextAnswer(BaseModel):
    """Final answer to the user, with suggested follow-up prompts."""

    content: str = Field(description="The answer text to show the user.")
    follow_ups: list[str] = Field(
        default_factory=list,
        description=(
            "Exactly 3 short prompts the user is likely to send next, in their "
            "voice and the answer's language. Chip-sized (at most 8 words each)."
        ),
    )


@dataclass
class AgentDeps:
    conversation_id: str


# Every run ends as either a final answer (text + follow-up chips) or a request
# for tool approval.
AgentOutput = TextAnswer | DeferredToolRequests


def build_agent(model: Model | str | None = None) -> Agent[AgentDeps, AgentOutput]:
    agent: Agent[AgentDeps, AgentOutput] = Agent(
        model or settings.resolved_model,
        deps_type=AgentDeps,
        output_type=[TextAnswer, DeferredToolRequests],
        instructions=INSTRUCTIONS,
    )

    @agent.tool
    async def list_tasks(ctx: RunContext[AgentDeps]) -> list[db.TaskItem]:
        """List all tasks with their id, title, and completion status."""
        return await db.list_tasks(ctx.deps.conversation_id)

    @agent.tool
    async def add_task(ctx: RunContext[AgentDeps], title: str) -> db.TaskItem:
        """Add a new task with the given title."""
        return await db.add_task(ctx.deps.conversation_id, title)

    @agent.tool
    async def complete_task(ctx: RunContext[AgentDeps], task_id: int) -> db.TaskItem:
        """Mark the task with the given id as done."""
        task = await db.complete_task(ctx.deps.conversation_id, task_id)
        if task is None:
            raise ValueError(f"No task with id {task_id}")
        return task

    @agent.tool(requires_approval=True)
    async def delete_task(ctx: RunContext[AgentDeps], task_id: int) -> str:
        """Permanently delete the task with the given id. Requires user approval."""
        deleted = await db.delete_task(ctx.deps.conversation_id, task_id)
        if not deleted:
            raise ValueError(f"No task with id {task_id}")
        return f"Task {task_id} deleted"

    @agent.tool(requires_approval=True)
    async def clear_all_tasks(ctx: RunContext[AgentDeps]) -> str:
        """Permanently delete ALL tasks. Requires user approval."""
        count = await db.clear_tasks(ctx.deps.conversation_id)
        return f"Deleted {count} tasks"

    @agent.tool
    async def schedule_reminder(
        ctx: RunContext[AgentDeps], message: str, delay_seconds: int
    ) -> str:
        """Schedule a reminder notification for this conversation.

        The reminder is delivered to every connected client after the delay
        (seconds, capped at one hour).
        """
        delay = min(max(delay_seconds, 0), 3600)
        reminders.schedule(ctx.deps.conversation_id, message, delay)
        return f"Reminder scheduled in {delay} seconds"

    return agent


agent = build_agent()
