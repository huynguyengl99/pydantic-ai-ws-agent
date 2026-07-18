import os

os.environ.setdefault("AGENT_MODEL", "test")

from pathlib import Path

import pytest

from app import db


@pytest.fixture(autouse=True)
async def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    await db.init_db()
