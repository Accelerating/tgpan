import asyncio
import json

import httpx
import pytest

from app.common.config import Settings
from app.common.security import Secrets
from app.storage.service import StorageTestFailure, TelegramError, safe_error
from app.storage.telegram import TelegramStorage


@pytest.fixture
def adapter(tmp_path):
    settings = Settings(proxy_url="", data_dir=tmp_path)
    settings.prepare()
    secrets = Secrets(tmp_path)
    config = {
        "id": "bot",
        "channel": "-1001234567890",
        "token": secrets.cipher.encrypt(b"123456:private-token").decode(),
    }
    return settings, secrets, config


def test_multipart_upload_persists_both_identifiers_and_progress(adapter):
    settings, secrets, config = adapter
    path = settings.data_dir / "file.bin"
    content = b"upload-content" * 10000
    path.write_bytes(content)
    progress = []

    async def handler(request):
        assert request.url.path.endswith("/sendDocument")
        assert request.headers["content-type"].startswith("multipart/form-data;")
        body = await request.aread()
        assert int(request.headers["content-length"]) == len(body)
        assert content in body and config["channel"].encode() in body
        return httpx.Response(
            200, json={"ok": True, "result": {"message_id": 42, "document": {"file_id": "stored-id"}}}
        )

    async def report(current, total):
        progress.append((current, total))

    storage = TelegramStorage(settings, secrets, httpx.MockTransport(handler))
    result = asyncio.run(storage.upload(config, path, "file.bin", report))
    assert result.message_id == 42 and result.file_id == "stored-id"
    assert len(progress) >= 2 and progress[-1] == (len(content), len(content))


@pytest.mark.parametrize("range_supported", [True, False])
def test_download_range_and_full_response_fallback(adapter, range_supported):
    settings, secrets, config = adapter
    content = bytes(range(256)) * 800
    offset, length = 8001, 90001
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/getFile"):
            assert json.loads(request.content) == {"file_id": "persistent-file-id"}
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "documents/file_1.bin"}})
        assert request.headers["range"] == f"bytes={offset}-{offset + length - 1}"
        assert request.url.host == "api.telegram.org"
        if range_supported:
            return httpx.Response(
                206,
                content=content[offset : offset + length],
                headers={"Content-Range": f"bytes {offset}-{offset + length - 1}/{len(content)}"},
            )
        return httpx.Response(200, content=content)

    storage = TelegramStorage(settings, secrets, httpx.MockTransport(handler))

    async def run():
        chunks = [chunk async for chunk in storage.download(config, "persistent-file-id", offset, length)]
        assert all(len(chunk) <= 65536 for chunk in chunks)
        return b"".join(chunks)

    assert asyncio.run(run()) == content[offset : offset + length]
    assert len(seen) == 2


def test_bot_api_errors_are_safe_and_deletion_is_idempotent(adapter):
    settings, secrets, config = adapter

    def missing(request):
        return httpx.Response(
            400,
            json={"ok": False, "error_code": 400, "description": "Bad Request: message to delete not found"},
        )

    storage = TelegramStorage(settings, secrets, httpx.MockTransport(missing))
    asyncio.run(storage.delete(config, 999))
    assert "48 小时" in safe_error(TelegramError(400, "Bad Request: message can't be deleted"))
    assert "37 秒" in safe_error(TelegramError(429, "private-token", 37))
    assert "private-token" not in safe_error(TelegramError(400, "private-token"))

    def limited(request):
        return httpx.Response(429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 37}})

    storage.transport = httpx.MockTransport(limited)
    with pytest.raises(TelegramError) as caught:
        asyncio.run(storage.delete(config, 42))
    assert caught.value.retry_after == 37


def test_connection_test_checks_permissions_and_returns_partial_steps(adapter):
    settings, secrets, config = adapter
    content = b"tgpan connection test\n"
    calls = []

    async def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        result = {
            "getMe": {"id": 123456, "is_bot": True, "username": "test_bot"},
            "getChat": {"type": "channel", "title": "Private drive"},
            "getChatMember": {
                "status": "administrator",
                "can_post_messages": True,
                "can_delete_messages": True,
            },
            "sendDocument": {"message_id": 42, "document": {"file_id": "test-file"}},
            "getFile": {"file_path": "documents/test.txt"},
            "deleteMessage": True,
        }
        if method == "test.txt":
            return httpx.Response(200, content=content)
        await request.aread()
        return httpx.Response(200, json={"ok": True, "result": result[method]})

    storage = TelegramStorage(settings, secrets, httpx.MockTransport(handler))
    assert len(asyncio.run(storage.test(config))) == 5
    assert calls[-1] == "deleteMessage"

    async def denied(request):
        if request.url.path.endswith("/getChatMember"):
            return httpx.Response(200, json={"ok": True, "result": {"status": "member"}})
        return await handler(request)

    storage.transport = httpx.MockTransport(denied)
    with pytest.raises(StorageTestFailure) as caught:
        asyncio.run(storage.test(config))
    assert len(caught.value.steps) == 1 and "管理员" in caught.value.error


def test_download_rejects_incomplete_or_wrong_ranges(adapter):
    settings, secrets, config = adapter

    def handler(request):
        if request.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "documents/file.bin"}})
        return httpx.Response(206, content=b"wrong", headers={"Content-Range": "bytes 0-4/20"})

    storage = TelegramStorage(settings, secrets, httpx.MockTransport(handler))

    async def run():
        return b"".join([chunk async for chunk in storage.download(config, "file", 10, 5)])

    with pytest.raises(ValueError, match="范围"):
        asyncio.run(run())


def test_storage_block_limit_and_database_migration(tmp_path):
    from app.common.db import Database

    settings = Settings(proxy_url="", data_dir=tmp_path)
    assert settings.block_size == 16 * 1024**2
    with pytest.raises(ValueError):
        Settings(block_size=20 * 1024**2)
    db = Database(settings.database_url, settings.database_schema)
    db.open()
    try:
        db.migrate()
        db.migrate()
        from app.common.migrations import migration_files
        assert db.one("SELECT version FROM schema_version")["version"] == max(migration_files())
        assert db.one("SELECT count(*) FROM offline_settings")["count"] == 1
    finally:
        db.close()
