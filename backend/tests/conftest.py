import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.common.config import Settings
from app.common.security import new_id, passwords
from app.main import create_app
from app.storage.base import StoredFile


class FakeStorage:
    def __init__(self):
        self.messages = {}
        self.blocked = False
        self.fail = False
        self.next_id = 1

    async def upload(self, config, path, name, progress):
        while self.blocked:
            await asyncio.sleep(0.01)
        if self.fail:
            raise ConnectionError("secret token must not appear in responses")
        data = Path(path).read_bytes()
        identity = self.next_id
        self.next_id += 1
        self.messages[identity] = data
        await progress(len(data), len(data))
        return StoredFile(identity, str(identity))

    async def download(self, config, message_id, offset, length):
        yield self.messages[int(message_id)][offset : offset + length]

    async def delete(self, config, message_id):
        self.messages.pop(message_id, None)

    async def test(self, config):
        return [{"step": "模拟测试", "ok": True, "detail": "ok"}]


@pytest.fixture
def setup(tmp_path):
    settings = Settings(proxy_url="", data_dir=tmp_path, block_size=8192, chunk_size=4096, temp_limit=32768)
    storage = FakeStorage()
    app = create_app(settings, storage)
    with TestClient(app) as client:
        client.headers["Accept-Language"] = "zh-CN"
        identity = new_id()
        app.state.db.execute(
            "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)",
            (identity, "admin", passwords.hash("test-password-123"), 1, 0, time.time()),
        )
        response = client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        config = client.post(
            "/api/storage",
            json={"name": "private", "token": "123456:" + "x" * 32, "channel": "-1001234567890"},
        )
        assert config.status_code == 201, config.text
        yield client, app, storage


@pytest.fixture(autouse=True)
def database_schema(monkeypatch):
    """Use the configured database, isolating each test in a disposable schema."""
    import uuid

    import psycopg
    from psycopg import sql

    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(Settings().database_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {} ").format(sql.Identifier(schema)))
        monkeypatch.setenv("TGPAN_DATABASE_SCHEMA", schema)
        try:
            yield schema
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
