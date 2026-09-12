from ag_ui.core import CustomEvent, EventType

from app.assistant.topic import TaskletTopic

NOTIFICATION = "notification"


async def notify_conversation(conversation_id: str, title: str, body: str) -> None:
    """Push a notification into a conversation from outside any connection.

    AG-UI has no notification event, so it travels as ``CUSTOM``: the protocol's
    own escape hatch, which an AG-UI client can ignore without breaking.
    """
    await TaskletTopic.emit_to_thread(
        conversation_id,
        CustomEvent(
            type=EventType.CUSTOM,
            name=NOTIFICATION,
            value={"title": title, "body": body},
        ),
    )
