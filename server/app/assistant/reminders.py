import asyncio

# Keep strong references so scheduled jobs aren't garbage-collected mid-sleep.
_tasks: set[asyncio.Task[None]] = set()


def schedule(conversation_id: str, message: str, delay_seconds: float) -> None:
    """Fire a notification into the conversation after a delay.

    In-process on purpose — the demo runs with zero infrastructure. A real
    worker (ARQ, Celery, cron) does exactly the same thing: sleep somewhere
    else, then emit into the thread by id.
    """
    task = asyncio.create_task(_fire(conversation_id, message, delay_seconds))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _fire(conversation_id: str, message: str, delay_seconds: float) -> None:
    await asyncio.sleep(delay_seconds)
    # Imported lazily: the topic module imports the agent package at startup.
    from app.assistant.notify import notify_conversation

    await notify_conversation(conversation_id, "Reminder", message)
