from ag_ui.core import CustomEvent, EventType

NOTIFICATION = "notification"


def notification_event(title: str, body: str) -> CustomEvent:
    """AG-UI has no notification event, so it travels as ``CUSTOM``: the protocol's
    own escape hatch, which an AG-UI client can ignore without breaking."""
    return CustomEvent(
        type=EventType.CUSTOM,
        name=NOTIFICATION,
        value={"title": title, "body": body},
    )


async def notify_conversation(conversation_id: str, title: str, body: str) -> None:
    """Push a notification into a conversation from outside any connection."""
    # Imported here because the topic builds notifications of its own, and the two
    # modules would otherwise import each other.
    from app.assistant.topic import TaskletTopic  # noqa: PLC0415

    await TaskletTopic.emit_to_thread(conversation_id, notification_event(title, body))
