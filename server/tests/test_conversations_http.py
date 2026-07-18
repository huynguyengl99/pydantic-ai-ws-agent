from httpx import ASGITransport, AsyncClient

from app import db
from app.main import app


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_conversations_newest_first() -> None:
    await db.save_history("conv-old", "[]", "First conversation")
    await db.save_history("conv-new", "[]", "Second conversation")

    async with client() as http:
        response = await http.get("/conversations")

    assert response.status_code == 200
    conversations = response.json()
    assert [c["id"] for c in conversations] == ["conv-new", "conv-old"]
    assert conversations[0]["title"] == "Second conversation"
    assert conversations[1]["updated_at"]


async def test_title_keeps_first_value() -> None:
    await db.save_history("conv-keep", "[]", "Original title")
    await db.save_history("conv-keep", "[]", "Later title")

    conversations = await db.list_conversations()
    assert conversations[0].title == "Original title"


async def test_delete_conversation_removes_history_and_tasks() -> None:
    await db.save_history("conv-del", "[]", "To delete")
    await db.add_task("conv-del", "A task")

    async with client() as http:
        response = await http.delete("/conversations/conv-del")
        assert response.json() == {"deleted": True}

        assert await db.load_history("conv-del") is None
        assert await db.list_tasks("conv-del") == []

        second = await http.delete("/conversations/conv-del")
        assert second.status_code == 404
