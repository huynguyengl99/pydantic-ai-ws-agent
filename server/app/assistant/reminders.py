import asyncio

# Keep strong references so scheduled jobs aren't garbage-collected mid-sleep.
_tasks: set[asyncio.Task[None]] = set()


def schedule(conversation_id: str, message: str, delay_seconds: float) -> None:
    """Fire a notification into the conversation group after a delay.

    In-process on purpose — the demo runs with zero infrastructure. A real
    worker (ARQ, Celery, cron) does exactly the same thing: sleep somewhere
    else, then call `AgentConsumer.broadcast_event` with the same message.
    """
    task = asyncio.create_task(_fire(conversation_id, message, delay_seconds))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _fire(conversation_id: str, message: str, delay_seconds: float) -> None:
    await asyncio.sleep(delay_seconds)
    # Imported lazily: the consumer module imports the agent package at startup.
    from app.assistant.consumer import AgentConsumer, conversation_group
    from app.assistant.messages import NotificationMessage, NotificationPayload

    await AgentConsumer.broadcast_event(
        NotificationMessage(
            payload=NotificationPayload(title="Reminder", body=message)
        ),
        groups=conversation_group(conversation_id),
    )
