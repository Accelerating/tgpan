import asyncio
import base64
import re
import shutil
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.common.security import new_id, passwords
from app.offline.service import OfflineWorker, files_for, task_directory
from app.offline.torrent import torrent_files


def encode(value):
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(map(encode, value)) + b"e"
    return b"d" + b"".join(encode(key) + encode(value[key]) for key in sorted(value)) + b"e"


def torrent(paths=((b"a.bin", 21000), (b"nested/b.bin", 7000))):
    return encode(
        {
            b"info": {
                b"name": b"collection",
                b"piece length": 16384,
                b"pieces": b"x" * 40,
                b"files": [{b"path": path.split(b"/"), b"length": size} for path, size in paths],
            }
        }
    )


def wait_task(client, identity, expected, timeout=12, observed=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = next(task for task in client.get("/api/offline").json() if task["id"] == identity)
        if observed is not None:
            observed.append(task)
        if task["state"] in expected:
            return task
        time.sleep(0.08)
    raise AssertionError(task)


@pytest.fixture
def offline(setup, monkeypatch):
    client, app, storage = setup
    monkeypatch.setattr(app.state.components, "executable", lambda: "/fake/aria2c")

    async def inspect(source):
        return source, 21000, False

    async def download(self, task, args, metadata=False):
        root = task_directory(self.state, task["id"])
        if metadata:
            (root / "metadata" / "metadata.torrent").write_bytes(torrent())
            return
        for file in files_for(self.state, task["id"]):
            if file["selected"]:
                path = root / "contents" / file["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(bytes([file["position"]]) * file["size"])

    monkeypatch.setattr("app.offline.routes.inspect_http", inspect)
    monkeypatch.setattr("app.offline.service.inspect_http", inspect)
    monkeypatch.setattr(OfflineWorker, "download", download)
    return client, app, storage


def test_http_import_indexes_and_cleans_local_files(offline):
    client, app, storage = offline
    response = client.post("/api/offline", json={"sources": ["https://example.org/a.bin"]})
    assert response.status_code == 201, response.text
    identity = response.json()[0]["id"]
    task = wait_task(client, identity, {"complete", "error"})
    assert task["state"] == "complete", task
    assert task["stored"] == task["downloaded"] == task["total"] == 21000
    assert "source" not in task
    assert not task_directory(app.state, identity).exists()
    assert client.get("/api/transfers").json()["uploads"] == []
    node = client.get("/api/files").json()["items"][0]
    assert node["status"] == "ready"
    assert client.get(f"/api/files/{node['id']}/download").content == bytes([1]) * 21000
    assert len(storage.messages) == 3


def test_torrent_selection_preserves_tree_and_skips_unselected(offline):
    client, app, _ = offline
    response = client.post("/api/offline", json={"torrent": base64.b64encode(torrent()).decode()})
    assert response.status_code == 201, response.text
    task = response.json()[0]
    assert task["state"] == "selecting" and len(task["files"]) == 2
    assert client.post(f"/api/offline/{task['id']}/select", json={"positions": [2]}).status_code == 200
    result = wait_task(client, task["id"], {"complete", "error"})
    assert result["state"] == "complete", result
    files = app.state.db.all("SELECT name,size FROM nodes WHERE kind='file'")
    assert files == [{"name": "b.bin", "size": 7000}]
    assert app.state.db.one("SELECT name FROM nodes WHERE name='nested'")


def test_magnet_resolves_before_file_selection(offline):
    client, _, _ = offline
    task = client.post("/api/offline", json={"sources": ["magnet:?xt=urn:btih:" + "a" * 40]}).json()[0]
    result = wait_task(client, task["id"], {"selecting", "error"})
    assert result["state"] == "selecting", result
    assert len(result["files"]) == 2


def test_failed_storage_retry_keeps_original_and_existing_upload(offline):
    client, app, storage = offline
    storage.fail = True
    task = client.post("/api/offline", json={"sources": ["https://example.org/a.bin"]}).json()[0]
    failed = wait_task(client, task["id"], {"error"})
    assert failed["phase"] == "store"
    source = task_directory(app.state, task["id"]) / "contents" / "a.bin"
    assert source.exists()
    old_upload = app.state.db.one("SELECT id FROM uploads")["id"]
    storage.fail = False
    assert client.post(f"/api/offline/{task['id']}/retry").status_code == 200
    finished = wait_task(client, task["id"], {"complete", "error"})
    assert finished["state"] == "complete", finished
    assert app.state.db.all("SELECT id FROM uploads") == [{"id": old_upload}]
    assert not source.exists()


def test_cancel_keeps_completed_files_and_removes_unfinished(offline):
    client, app, storage = offline
    storage.blocked = True
    task = client.post("/api/offline", json={"sources": ["https://example.org/a.bin"]}).json()[0]
    wait_task(client, task["id"], {"storing"})
    assert client.post(f"/api/offline/{task['id']}/cancel").status_code == 200
    assert not task_directory(app.state, task["id"]).exists()
    storage.blocked = False
    deadline = time.monotonic() + 5
    while storage.messages and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.get("/api/files").json()["items"] == []
    assert client.delete(f"/api/offline/{task['id']}").status_code == 200


def test_size_limits_are_reported_before_download(offline, monkeypatch):
    client, app, _ = offline
    app.state.settings.max_file_size = 100
    assert client.post("/api/offline", json={"sources": ["https://example.org/a.bin"]}).status_code == 413
    assert client.get("/api/offline").json() == []
    task = client.post("/api/offline", json={"torrent": base64.b64encode(torrent()).decode()}).json()[0]
    response = client.post(f"/api/offline/{task['id']}/select", json={"positions": [1]})
    assert response.status_code == 413
    assert "大小超出限制" in response.json()["detail"]
    assert app.state.db.all("SELECT id FROM uploads") == []


def test_paused_task_resumes_without_reupload(offline):
    client, app, storage = offline
    storage.blocked = True
    task = client.post("/api/offline", json={"sources": ["https://example.org/a.bin"]}).json()[0]
    wait_task(client, task["id"], {"storing"})
    assert client.post(f"/api/offline/{task['id']}/pause").status_code == 200
    assert wait_task(client, task["id"], {"paused"})["phase"] == "store"
    storage.blocked = False
    time.sleep(0.2)
    assert wait_task(client, task["id"], {"paused"})["state"] == "paused"
    assert client.post(f"/api/offline/{task['id']}/resume").status_code == 200
    assert wait_task(client, task["id"], {"complete", "error"})["state"] == "complete"


def test_task_privacy_and_admin_component_permissions(offline):
    client, app, _ = offline
    task = client.post("/api/offline", json={"torrent": base64.b64encode(torrent()).decode()}).json()[0]
    app.state.db.execute(
        "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)",
        (
            new_id(),
            "other",
            passwords.hash("test-password-123"),
            0,
            0,
            time.time(),
        ),
    )
    csrf = client.post("/api/auth/login", json={"username": "other", "password": "test-password-123"}).json()[
        "csrf"
    ]
    client.headers["X-CSRF-Token"] = csrf
    assert client.get("/api/offline").json() == []
    assert client.post(f"/api/offline/{task['id']}/cancel").status_code == 404
    assert client.get("/api/components/aria2").status_code == 403
    assert client.post("/api/components/aria2/install").status_code == 403
    assert (
        client.patch(
            "/api/offline/settings", json={"concurrency": 2, "max_bytes": 10000000, "reserve_bytes": 0}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("path", [b"../secret", b"/secret", b"a\\b", b"a/../b", b"a\x00b"])
def test_torrent_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        torrent_files(torrent(((path, 1),)))


def test_torrent_rejects_symlinks_duplicate_paths_and_v2():
    with pytest.raises(ValueError):
        torrent_files(torrent(((b"same", 1), (b"same", 2))))
    with pytest.raises(ValueError):
        torrent_files(encode({b"info": {b"name": b"x", b"meta version": 2}}))
    with pytest.raises(ValueError):
        torrent_files(
            encode(
                {
                    b"info": {
                        b"name": b"x",
                        b"pieces": b"",
                        b"files": [
                            {b"path": [b"link"], b"length": 1, b"attr": b"l", b"symlink path": [b"secret"]},
                        ],
                    }
                }
            )
        )


@pytest.mark.parametrize("paused", [False, True])
def test_full_service_restart_resumes_local_import(tmp_path, monkeypatch, paused):
    from conftest import FakeStorage
    from fastapi.testclient import TestClient

    from app.common.config import Settings
    from app.main import create_app

    settings = Settings(data_dir=tmp_path, block_size=8192, chunk_size=4096, temp_limit=32768)
    storage = FakeStorage()
    storage.blocked = True
    app = create_app(settings, storage)

    async def download(self, task, args, metadata=False):
        for file in files_for(self.state, task["id"]):
            if file["selected"]:
                path = task_directory(self.state, task["id"]) / "contents" / file["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"r" * file["size"])

    monkeypatch.setattr(OfflineWorker, "download", download)
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.components, "executable", lambda: "/fake/aria2c")
        app.state.db.execute(
            "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)",
            (
                new_id(),
                "restart",
                passwords.hash("test-password-123"),
                1,
                0,
                time.time(),
            ),
        )
        login = client.post(
            "/api/auth/login", json={"username": "restart", "password": "test-password-123"}
        ).json()
        client.headers.update({"X-CSRF-Token": login["csrf"], "Accept-Language": "zh-CN"})
        client.post(
            "/api/storage", json={"name": "test", "token": "123456:" + "x" * 32, "channel": "-1001234567890"}
        )
        task = client.post("/api/offline", json={"torrent": base64.b64encode(torrent()).decode()}).json()[0]
        client.post(f"/api/offline/{task['id']}/select", json={"positions": [1]})
        wait_task(client, task["id"], {"storing"})
        if paused:
            client.post(f"/api/offline/{task['id']}/pause")
        cookies = dict(client.cookies)
    storage.blocked = False
    restarted = create_app(settings, storage)
    with TestClient(restarted) as client:
        client.cookies.update(cookies)
        client.headers.update({"X-CSRF-Token": login["csrf"], "Accept-Language": "zh-CN"})
        if paused:
            assert wait_task(client, task["id"], {"paused"})["state"] == "paused"
            assert client.post(f"/api/offline/{task['id']}/resume").status_code == 200
        result = wait_task(client, task["id"], {"complete", "error"})
        assert result["state"] == "complete", result["error"]
        assert len(restarted.state.db.all("SELECT id FROM uploads")) == 1
        assert len(storage.messages) == 3
        assert not task_directory(restarted.state, task["id"]).exists()


def test_http_proxy_blocks_private_destinations_and_requires_auth():
    import httpx

    from app.offline.proxy import DownloadProxy

    async def run():
        async with DownloadProxy() as proxy:
            async with httpx.AsyncClient(proxy=proxy.url, trust_env=False) as client:
                assert (await client.get("http://127.0.0.1:1/private")).status_code == 403
                with pytest.raises(httpx.ProxyError):
                    await client.get("https://127.0.0.1:1/private")
            async with httpx.AsyncClient(
                proxy=proxy.url.replace(proxy.token + ":@", ""), trust_env=False
            ) as client:
                assert (await client.get("http://example.org/")).status_code == 403

    asyncio.run(run())


def test_signed_get_url_can_reject_head(monkeypatch):
    import httpx

    from app.offline.network import inspect_http

    original_client = httpx.AsyncClient

    async def public(value):
        return value

    monkeypatch.setattr("app.offline.network.public_url", public)
    monkeypatch.setattr(
        "app.offline.network.httpx.AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, headers={"Content-Length": "99"})
            ),
            trust_env=False,
        ),
    )
    source = "https://example.org/file.bin?signature=get-only"
    assert asyncio.run(inspect_http(source)) == (source, None, False)


@pytest.mark.parametrize("already_closing", [False, True])
def test_proxy_handles_disconnect_while_rejecting_incomplete_request(already_closing):
    from app.offline.proxy import DownloadProxy

    class DisconnectedWriter:
        closed = False

        def is_closing(self):
            return already_closing

        def write(self, data):
            raise RuntimeError("uvloop transport is closed")

        async def drain(self):
            raise ConnectionResetError("Connection lost")

        def close(self):
            self.closed = True

    async def run():
        async with DownloadProxy() as proxy:
            reader = asyncio.StreamReader()
            reader.feed_eof()
            writer = DisconnectedWriter()
            await proxy.accept(reader, writer)
            assert writer.closed
            assert not proxy.connections

    asyncio.run(run())


def test_failed_component_update_preserves_previous_version(setup, monkeypatch):
    _, app, _ = setup
    manager = app.state.components
    root = manager.root
    old = root / "aria2-old"
    (old / "bin").mkdir(parents=True)
    (old / "bin" / "aria2c").write_text("old version")
    (root / "aria2").symlink_to(old.name)
    (root / "micromamba").write_text("test installer")

    async def failed_command(*args, **kwargs):
        return 1, "private installer diagnostic"

    monkeypatch.setattr("app.components.service.command", failed_command)
    asyncio.run(manager._install())
    assert manager.status == "error"
    assert (root / "aria2").resolve() == old
    assert "private installer diagnostic" not in manager.error


def test_recovery_finishes_committed_indexes_before_local_cleanup(offline):
    client, app, _ = offline
    task = client.post("/api/offline", json={"sources": ["https://example.org/a.bin"]}).json()[0]
    result = wait_task(client, task["id"], {"complete", "error"})
    assert result["state"] == "complete"
    source = task_directory(app.state, task["id"]) / "contents" / "a.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(bytes([1]) * 21000)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE offline_tasks SET state='paused' WHERE id=%s", (task["id"],))
        conn.execute("UPDATE offline_files SET complete=0 WHERE task_id=%s", (task["id"],))
        conn.execute("UPDATE uploads SET state='receiving'")
        conn.execute("UPDATE nodes SET status='uploading' WHERE kind='file'")
    app.state.worker.recover()
    assert app.state.db.one("SELECT state FROM uploads")["state"] == "complete"
    assert app.state.db.one("SELECT status FROM nodes WHERE kind='file'")["status"] == "ready"
    assert client.post(f"/api/offline/{task['id']}/resume").status_code == 200
    result = wait_task(client, task["id"], {"complete", "error"})
    assert result["state"] == "complete", result["error"]
    assert not source.exists()


@pytest.mark.skipif(not shutil.which("aria2c"), reason="aria2c is optional")
def test_real_aria2_http_pipeline(setup, monkeypatch):
    client, app, _ = setup
    content = b"real aria2 pipeline\n" * 70000
    app.state.settings.block_size = 256 * 1024
    app.state.settings.temp_limit = 1024**2
    from app.common.processes import command

    diagnostics = []

    async def checked_command(*args, **kwargs):
        result = await command(*args, **kwargs)
        diagnostics.append(re.sub(r"http://\S+", "[URL]", result[1]))
        return result

    monkeypatch.setattr("app.offline.service.command", checked_command)

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()

        def do_GET(self):
            self.do_HEAD()
            for offset in range(0, len(content), 65536):
                self.wfile.write(content[offset : offset + 65536])
                self.wfile.flush()
                time.sleep(0.12)

        def log_message(self, *args):
            pass

    async def local_for_test(value):
        return value

    monkeypatch.setattr("app.offline.network.public_url", local_for_test)

    async def local_addresses(host, port):
        return await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)

    monkeypatch.setattr("app.offline.proxy.public_addresses", local_addresses)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = client.post(
            "/api/offline", json={"sources": [f"http://127.0.0.1:{server.server_port}/real.bin"]}
        )
        assert response.status_code == 201, response.text
        observed = []
        task = wait_task(client, response.json()[0]["id"], {"complete", "error"}, observed=observed)
        assert task["state"] == "complete", "\n".join(diagnostics) or task["error"]
        node = client.get("/api/files").json()["items"][0]
        assert client.get(f"/api/files/{node['id']}/download").content == content
        assert any(item["download_speed"] > 0 and item["downloaded"] > 0 for item in observed), diagnostics
    finally:
        server.shutdown()
        server.server_close()
