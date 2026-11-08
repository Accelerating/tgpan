import asyncio
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
import pytest
from conftest import FakeStorage
from fastapi.testclient import TestClient
from test_drive import upload_file, wait_for

from app.accounts import routes as accounts
from app.common.config import Settings
from app.common.security import passwords
from app.main import create_app


def test_unknown_login_attempts_do_not_lock_other_accounts(setup):
    client, _, _ = setup
    client.cookies.clear()
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/login", json={"username": "missing", "password": "wrong-password"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "test-password-123"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("trusted", [False, True])
def test_login_source_only_accepts_forwarded_addresses_from_trusted_proxy(setup, trusted):
    _, app, _ = setup
    app.state.settings.trusted_proxies = "10.0.0.1/32" if trusted else ""
    guest = TestClient(app, client=("10.0.0.1", 5000))
    try:
        for _ in range(10):
            result = guest.post(
                "/api/auth/login",
                json={"username": "ADMIN", "password": "wrong-password"},
                headers={"X-Forwarded-For": "198.51.100.1"},
            )
            assert result.status_code == 401
        result = guest.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-password-123"},
            headers={"X-Forwarded-For": "198.51.100.2"},
        )
        assert result.status_code == (200 if trusted else 429)
    finally:
        guest.close()


@pytest.mark.parametrize("disable", [False, True])
def test_inflight_login_cannot_survive_password_reset_or_disabling(setup, monkeypatch, disable):
    client, app, _ = setup
    identity = client.get("/api/auth/me").json()["user"]["id"]
    original = accounts.run_in_threadpool
    verified, release = threading.Event(), threading.Event()

    async def delayed(function, *args, **kwargs):
        result = await original(function, *args, **kwargs)
        if getattr(function, "__name__", "") == "verify":
            verified.set()
            await asyncio.to_thread(release.wait, 3)
        return result

    monkeypatch.setattr(accounts, "run_in_threadpool", delayed)
    guest = TestClient(app)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            login = pool.submit(
                guest.post, "/api/auth/login", json={"username": "admin", "password": "test-password-123"}
            )
            try:
                assert verified.wait(2)
                if disable:
                    app.state.db.execute("UPDATE users SET disabled=1 WHERE id=?", (identity,))
                else:
                    assert (
                        client.patch(
                            f"/api/users/{identity}", json={"password": "changed-password-456"}
                        ).status_code
                        == 200
                    )
            finally:
                release.set()
            assert login.result(timeout=3).status_code == 401
        assert guest.get("/api/auth/me").status_code == 401
    finally:
        guest.close()


@asynccontextmanager
async def async_client(tmp_path, storage=None):
    storage = storage or FakeStorage()
    app = create_app(
        Settings(
            data_dir=tmp_path,
            proxy_url="",
            public_origin="",
            secure_cookie=False,
            block_size=8192,
            chunk_size=4096,
            temp_limit=32768,
        ),
        storage,
    )
    async with app.router.lifespan_context(app):
        app.state.db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?)",
            ("audit", "admin", passwords.hash("test-password-123"), 1, 0, time.time()),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/auth/login", json={"username": "admin", "password": "test-password-123"}
            )
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
            config = await client.post(
                "/api/storage",
                json={"name": "fake", "token": "123456:" + "x" * 32, "channel": "-1001234567890"},
            )
            yield client, app, config.json()


def test_slow_upload_does_not_block_revocation_or_cancellation(tmp_path):
    async def probe():
        async with async_client(tmp_path) as (client, app, _):
            empty = await client.post(
                "/api/uploads", json={"name": "empty.txt", "size": 0, "fingerprint": "0" * 64}
            )
            share = await client.post("/api/shares", json={"node_id": empty.json()["node_id"]})
            task = (
                await client.post(
                    "/api/uploads", json={"name": "slow.bin", "size": 8192, "fingerprint": "1" * 64}
                )
            ).json()
            started, release = asyncio.Event(), asyncio.Event()
            content = b"x" * 4096

            async def slow_body():
                yield content[:1]
                started.set()
                await release.wait()
                yield content[1:]

            uploading = asyncio.create_task(
                client.put(
                    f"/api/uploads/{task['id']}/chunks",
                    content=slow_body(),
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-Chunk-SHA256": hashlib.sha256(content).hexdigest(),
                    },
                )
            )
            try:
                await asyncio.wait_for(started.wait(), 2)
                assert not app.state.mutation_lock.locked()
                duplicate = await asyncio.wait_for(
                    client.put(
                        f"/api/uploads/{task['id']}/chunks",
                        content=content,
                        headers={
                            "Content-Type": "application/octet-stream",
                            "X-Chunk-SHA256": hashlib.sha256(content).hexdigest(),
                        },
                    ),
                    1,
                )
                assert duplicate.status_code == 429
                revoke = await asyncio.wait_for(client.delete(f"/api/shares/{share.json()['id']}"), 1)
                assert revoke.status_code == 200
                cancel = await asyncio.wait_for(client.post(f"/api/uploads/{task['id']}/cancel"), 1)
                assert cancel.status_code == 200
                purge = await client.post(
                    "/api/files/batch", json={"ids": [task["node_id"]], "action": "purge"}
                )
                assert purge.status_code == 200
            finally:
                release.set()
            assert (await asyncio.wait_for(uploading, 3)).status_code == 404
            assert app.state.upload_reservations == {}
            assert not list((tmp_path / "uploads").iterdir())

    asyncio.run(probe())


def test_connection_test_does_not_hold_mutation_lock_and_protects_config(tmp_path):
    class SlowStorage(FakeStorage):
        async def test(self, config):
            self.started.set()
            await self.release.wait()
            return []

    async def probe():
        storage = SlowStorage()
        storage.started, storage.release = asyncio.Event(), asyncio.Event()
        async with async_client(tmp_path, storage) as (client, app, config):
            testing = asyncio.create_task(client.post(f"/api/storage/{config['id']}/test"))
            try:
                await asyncio.wait_for(storage.started.wait(), 2)
                assert not app.state.mutation_lock.locked()
                assert (
                    await asyncio.wait_for(client.delete(f"/api/storage/{config['id']}"), 1)
                ).status_code == 409
                assert (await client.post(f"/api/storage/{config['id']}/test")).status_code == 429
                task = await asyncio.wait_for(
                    client.post(
                        "/api/uploads", json={"name": "empty.txt", "size": 0, "fingerprint": "0" * 64}
                    ),
                    1,
                )
                share = await asyncio.wait_for(
                    client.post("/api/shares", json={"node_id": task.json()["node_id"]}), 1
                )
                assert share.status_code == 201
                assert (
                    await asyncio.wait_for(client.delete(f"/api/shares/{share.json()['id']}"), 1)
                ).status_code == 200
            finally:
                storage.release.set()
            assert (await testing).status_code == 200
            assert app.state.testing_configs == set()

    asyncio.run(probe())


def test_api_docs_disabled_by_default(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, proxy_url="", enable_api_docs=False), FakeStorage())
    with TestClient(app) as guest:
        assert guest.get("/api/docs").status_code == 404
        assert guest.get("/api/openapi.json").status_code == 404


def test_public_read_errors_do_not_expose_storage_details(setup, monkeypatch):
    client, app, storage = setup
    task = upload_file(client, b"image", "image.png")
    wait_for(client, task["id"], "complete")
    share = client.post("/api/shares", json={"node_id": task["node_id"]}).json()

    async def failed(*args, **kwargs):
        raise ConnectionError("private storage details")
        yield b""

    monkeypatch.setattr(storage, "download", failed)
    guest = TestClient(app)
    try:
        token = share["path"].rsplit("/", 1)[-1]
        for action in ("preview", "download"):
            response = guest.get(f"/api/public/shares/{token}/{action}")
            assert response.status_code == 502
            assert response.json()["detail"] == "This file is temporarily unavailable. Please try again later."
            assert "Telegram" not in response.text and "private" not in response.text
        private = client.get(f"/api/files/{task['node_id']}/download")
        assert private.status_code == 502 and "Telegram" in private.json()["detail"]
    finally:
        guest.close()


def test_password_change_cannot_overwrite_a_concurrent_admin_reset(setup, monkeypatch):
    client, app, _ = setup
    target = client.post("/api/users", json={"username": "other", "password": "other-password"}).json()
    guest = TestClient(app)
    login = guest.post("/api/auth/login", json={"username": "other", "password": "other-password"}).json()
    guest.headers["X-CSRF-Token"] = login["csrf"]
    original = accounts.run_in_threadpool
    hashed, release = threading.Event(), threading.Event()

    async def delayed(function, *args, **kwargs):
        result = await original(function, *args, **kwargs)
        if getattr(function, "__name__", "") == "hash" and args[0] == "pending-password":
            hashed.set()
            await asyncio.to_thread(release.wait, 3)
        return result

    monkeypatch.setattr(accounts, "run_in_threadpool", delayed)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            changing = pool.submit(
                guest.post,
                "/api/auth/password",
                json={"current_password": "other-password", "password": "pending-password"},
            )
            try:
                assert hashed.wait(2)
                assert (
                    client.patch(
                        f"/api/users/{target['id']}", json={"password": "admin-new-password"}
                    ).status_code
                    == 200
                )
            finally:
                release.set()
            assert changing.result(timeout=3).status_code == 401
        assert passwords.verify(
            app.state.db.one("SELECT password FROM users WHERE id=?", (target["id"],))["password"],
            "admin-new-password",
        )
    finally:
        guest.close()


def test_parallel_receivers_reserve_space_and_release_capacity(tmp_path):
    async def probe():
        async with async_client(tmp_path) as (first, app, _):
            others = []
            for index in range(2):
                name = f"other{index}"
                await first.post("/api/users", json={"username": name, "password": "other-password"})
                client = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://testserver"
                )
                auth = await client.post(
                    "/api/auth/login", json={"username": name, "password": "other-password"}
                )
                client.headers["X-CSRF-Token"] = auth.json()["csrf"]
                await client.post(
                    "/api/storage",
                    json={"name": "fake", "token": "123456:" + "x" * 32, "channel": "-1001234567890"},
                )
                others.append(client)
            clients = [first, *others]
            release = asyncio.Event()
            started = [asyncio.Event(), asyncio.Event()]
            payload = b"x" * 4096
            tasks, requests = [], []
            headers = {
                "Content-Type": "application/octet-stream",
                "X-Chunk-SHA256": hashlib.sha256(payload).hexdigest(),
            }

            async def body(index):
                yield payload[:1]
                started[index].set()
                await release.wait()
                yield payload[1:]

            try:
                for index, client in enumerate(clients):
                    task = await client.post(
                        "/api/uploads", json={"name": "incoming.bin", "size": 8192, "fingerprint": "2" * 64}
                    )
                    tasks.append(task.json())
                    if index < 2:
                        requests.append(
                            asyncio.create_task(
                                client.put(
                                    f"/api/uploads/{tasks[-1]['id']}/chunks",
                                    content=body(index),
                                    headers=headers,
                                )
                            )
                        )
                        await asyncio.wait_for(started[index].wait(), 2)
                assert len(app.state.upload_reservations) == 2
                assert sum(app.state.upload_reservations.values()) == 16384
                rejected = await clients[2].put(
                    f"/api/uploads/{tasks[2]['id']}/chunks", content=payload, headers=headers
                )
                assert rejected.status_code == 429
            finally:
                release.set()
                replies = await asyncio.gather(*requests)
                for client in others:
                    await client.aclose()
            assert all(reply.status_code == 200 for reply in replies)
            assert app.state.upload_reservations == {}
            assert (
                sum(path.stat().st_size for path in (tmp_path / "uploads").iterdir())
                <= app.state.settings.temp_limit
            )

    asyncio.run(probe())
