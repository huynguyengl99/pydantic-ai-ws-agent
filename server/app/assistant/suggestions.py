from ag_ui.core import CustomEvent, EventType
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model

from app.config import settings

SUGGESTIONS = "suggestions"

INSTRUCTIONS = """\
Suggest exactly 3 short prompts the user is likely to send next, in their voice and
in the answer's language, each small enough for a chip (at most 8 words).

Ground them in the conversation and the real task list: refer to tasks by id or
title, suggest completing an open one, adding an obvious missing step, or setting a
reminder when timing matters. At most ONE may be destructive (delete / clear all).
Never suggest anything the assistant cannot do.
"""


class FollowUps(BaseModel):
    prompts: list[str] = Field(default_factory=list)


def build_suggester(model: Model | str | None = None) -> Agent[None, FollowUps]:
    return Agent(
        model or settings.resolved_model,
        output_type=FollowUps,
        instructions=INSTRUCTIONS,
    )


suggester = build_suggester()


async def follow_ups(messages: list[ModelMessage]) -> list[str]:
    """Chips for the answer just given.

    A second, cheap call rather than a field on the answer: v1 folded these into a
    structured output, which meant the reply could not stream as text. Streaming is
    worth more than one round trip, and a failure here costs only the chips.
    """
    if not messages:
        return []
    try:
        result = await suggester.run(
            "Suggest what the user might ask next.", message_history=messages
        )
    except Exception:  # noqa: BLE001 - chips are a nicety, never a failed run
        return []
    return [prompt for prompt in result.output.prompts if prompt.strip()][:3]


def suggestions_event(prompts: list[str]) -> CustomEvent:
    """AG-UI has no event for these, so they ride CUSTOM, which a client may ignore."""
    return CustomEvent(
        type=EventType.CUSTOM, name=SUGGESTIONS, value={"prompts": prompts}
    )
