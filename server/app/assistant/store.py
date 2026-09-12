from app import db
from app.ws_kits.conversation_store import ConversationStore


class SqliteConversationStore(ConversationStore):
    """The kit's store over the conversations table, which already holds the
    transcript as text and carries the title and timestamp the sidebar reads."""

    async def load(self, thread_id: str) -> str | None:
        return await db.load_history(thread_id)

    async def save(self, thread_id: str, conversation: str) -> None:
        await db.save_history(thread_id, conversation)

    async def delete(self, thread_id: str) -> None:
        await db.delete_conversation(thread_id)
