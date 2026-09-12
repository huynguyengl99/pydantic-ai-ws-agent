from typing import Any, ClassVar

from chanx.core.decorators import channel
from chanx.core.topic import Topic

from app.assistant.topic import TaskletTopic
from app.ws import BaseConsumer


@channel(
    name="agent",
    description="Pydantic AI task assistant speaking AG-UI over a WebSocket",
    tags=["agent", "ai", "ag-ui"],
)
class AgentConsumer(BaseConsumer):
    """One connection, any number of conversations: a client subscribes to
    ``agui:thread:<conversation_id>`` and drives the agent there."""

    topics: ClassVar[list[type[Topic[Any]]]] = [TaskletTopic]
