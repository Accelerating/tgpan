import hashlib
import time


def wait_for(client, identity, expected):
    for _ in range(200):
        task = client.get(f"/api/uploads/{identity}").json()
        if task.get("state") == expected:
            return task
        time.sleep(0.025)
    raise AssertionError(task)


def upload_file(client, content, name="file.bin", parent=None):
    task = client.post(
        "/api/uploads",
        json={
            "name": name,
            "size": len(content),
            "fingerprint": hashlib.sha256(content).hexdigest(),
            "parent_id": parent,
        },
    )
    assert task.status_code == 201, task.text
    task = task.json()
    for offset in range(task["received"], len(content), 4096):
        chunk = content[offset : offset + 4096]
        response = client.put(
            f"/api/uploads/{task['id']}/chunks?offset={offset}",
            content=chunk,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
            },
        )
        assert response.status_code == 200, response.text
    return task


def test_upload_range_recycle_and_cleanup(setup):
    client, app, storage = setup
    folder = client.post("/api/files/folders", json={"name": "文档"}).json()
    content = bytes(range(256)) * 90
    task = upload_file(client, content, "测试.bin", folder["id"])
    wait_for(client, task["id"], "complete")
    node = task["node_id"]
    response = client.get(f"/api/files/{node}/download")
    assert response.content == content
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    for header, expected in [
        ("bytes=8000-17000", content[8000:17001]),
        ("bytes=-20", content[-20:]),
        ("bytes=9000-", content[9000:]),
    ]:
        response = client.get(f"/api/files/{node}/download", headers={"Range": header})
        assert response.status_code == 206
        assert response.content == expected
    assert client.get(f"/api/files/{node}/download", headers={"Range": "bytes=999999-"}).status_code == 416
    assert client.patch(f"/api/files/{node}", json={"name": "renamed.bin"}).status_code == 200
    assert client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "trash"}).status_code == 200
    assert client.get(f"/api/files/{node}/download").status_code == 404
    assert (
        client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "restore"}).status_code == 200
    )
    assert client.get(f"/api/files/{node}/download").content == content
    client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "trash"})
    assert client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "purge"}).status_code == 200
    for _ in range(100):
        if not storage.messages:
            break
        time.sleep(0.05)
    assert not storage.messages


def test_permissions_csrf_and_session_revocation(setup):
    client, app, storage = setup
    folder = client.post("/api/files/folders", json={"name": "private"}).json()
    user = client.post("/api/users", json={"username": "other", "password": "another-password"}).json()
    admin_cookies, csrf = dict(client.cookies), client.headers["X-CSRF-Token"]
    client.cookies.clear()
    login = client.post("/api/auth/login", json={"username": "other", "password": "another-password"}).json()
    client.headers["X-CSRF-Token"] = login["csrf"]
    assert client.get("/api/files").json()["items"] == []
    assert client.patch(f"/api/files/{folder['id']}", json={"name": "hack"}).status_code == 404
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/storage").json() == []
    assert (
        client.post("/api/files/folders", json={"name": "x"}, headers={"X-CSRF-Token": "bad"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/files/folders", json={"name": "x"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    other_cookies = dict(client.cookies)
    client.cookies.clear()
    client.cookies.update(admin_cookies)
    client.headers["X-CSRF-Token"] = csrf
    assert client.patch(f"/api/users/{user['id']}", json={"disabled": True}).status_code == 200
    client.cookies.clear()
    client.cookies.update(other_cookies)
    assert client.get("/api/auth/me").status_code == 401


def test_resume_integrity_conflicts_and_cycles(setup):
    client, app, storage = setup
    content = b"a" * 12000
    body = {"name": "big.bin", "size": len(content), "fingerprint": hashlib.sha256(content).hexdigest()}
    task = client.post("/api/uploads", json=body).json()
    chunk = content[:4096]
    url = f"/api/uploads/{task['id']}/chunks?offset=0"
    assert client.put(url, content=chunk, headers={"X-Chunk-SHA256": "0" * 64}).status_code == 422
    assert client.get(f"/api/uploads/{task['id']}").json()["received"] == 0
    assert (
        client.put(
            url, content=chunk, headers={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()}
        ).status_code
        == 200
    )
    assert (
        client.put(
            url, content=chunk, headers={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()}
        ).status_code
        == 409
    )
    resumed = client.post("/api/uploads", json=body).json()
    assert resumed["id"] == task["id"] and resumed["received"] == 4096
    assert client.post("/api/files/folders", json={"name": "big.bin"}).status_code == 409
    parent = client.post("/api/files/folders", json={"name": "a"}).json()
    child = client.post("/api/files/folders", json={"name": "b", "parent_id": parent["id"]}).json()
    assert client.patch(f"/api/files/{parent['id']}", json={"parent_id": child["id"]}).status_code == 400
    assert client.post("/api/files/folders", json={"name": "../bad"}).status_code == 422
    assert (
        client.post("/api/uploads", json={**body, "name": "large", "size": 5_000_000_001}).status_code == 413
    )


def test_retry_cancel_and_protected_config(setup):
    client, app, storage = setup
    storage.fail = True
    task = upload_file(client, b"x" * 8192)
    failed = wait_for(client, task["id"], "error")
    assert "secret token" not in failed["error"]
    configs = client.get("/api/storage").json()
    assert "token" not in configs[0]
    assert client.delete(f"/api/storage/{configs[0]['id']}").status_code == 409
    storage.fail = False
    assert client.post(f"/api/uploads/{task['id']}/retry").status_code == 200
    wait_for(client, task["id"], "complete")
    other = client.post(
        "/api/uploads", json={"name": "cancel.bin", "size": 20000, "fingerprint": "1" * 64}
    ).json()
    assert client.post(f"/api/uploads/{other['id']}/cancel").status_code == 200
    assert client.get(f"/api/uploads/{other['id']}").json()["state"] == "cancelled"


def test_restart_recovers_acknowledged_chunks(setup):
    client, app, storage = setup
    task = client.post(
        "/api/uploads", json={"name": "resume.bin", "size": 12000, "fingerprint": "2" * 64}
    ).json()
    chunk = b"z" * 4096
    client.put(
        f"/api/uploads/{task['id']}/chunks?offset=0",
        content=chunk,
        headers={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()},
    )
    from app.transfers.service import block_path

    path = block_path(app.state, task["id"], 0)
    with path.open("ab") as out:
        out.write(b"unacknowledged tail")
    app.state.worker.recover()
    assert path.stat().st_size == 4096
    assert client.get(f"/api/uploads/{task['id']}").json()["received"] == 4096


def test_empty_file_and_restore_conflict(setup):
    client, app, storage = setup
    task = upload_file(client, b"", "empty.txt")
    assert client.get(f"/api/files/{task['node_id']}/download").content == b""
    folder = client.post("/api/files/folders", json={"name": "same"}).json()
    client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "trash"})
    client.post("/api/files/folders", json={"name": "same"})
    assert (
        client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "restore"}).status_code == 409
    )
    assert client.get("/api/files", params={"trash": True}).json()["items"][0]["id"] == folder["id"]


def test_backpressure_and_cancel_inflight_block(setup):
    client, app, storage = setup
    storage.blocked = True
    task = client.post(
        "/api/uploads", json={"name": "pressure.bin", "size": 40000, "fingerprint": "3" * 64}
    ).json()
    payload = b"x" * 4096
    headers = {"X-Chunk-SHA256": hashlib.sha256(payload).hexdigest()}
    for offset in range(0, 28672, 4096):
        response = client.put(
            f"/api/uploads/{task['id']}/chunks?offset={offset}", content=payload, headers=headers
        )
        assert response.status_code == 200, response.text
    response = client.put(f"/api/uploads/{task['id']}/chunks?offset=28672", content=payload, headers=headers)
    assert response.status_code == 429
    assert sum(path.stat().st_size for path in (app.state.settings.data_dir / "uploads").iterdir()) <= 32768
    assert client.post(f"/api/uploads/{task['id']}/cancel").status_code == 200
    storage.blocked = False
    for _ in range(200):
        if not app.state.worker.active_config and not storage.messages:
            break
        time.sleep(0.025)
    assert not storage.messages
    assert not list((app.state.settings.data_dir / "uploads").iterdir())
    assert (
        client.post("/api/files/batch", json={"ids": [task["node_id"]], "action": "restore"}).status_code
        == 409
    )


def test_cleanup_failure_retains_configuration_reference(setup):
    client, app, storage = setup
    task = upload_file(client, b"x" * 4096, "cleanup.bin")
    wait_for(client, task["id"], "complete")

    async def failure(config, message_id):
        raise ConnectionError("sensitive-detail")

    original = storage.delete
    storage.delete = failure
    client.post("/api/files/batch", json={"ids": [task["node_id"]], "action": "trash"})
    assert (
        client.post("/api/files/batch", json={"ids": [task["node_id"]], "action": "purge"}).status_code == 200
    )
    for _ in range(150):
        cleanup = client.get("/api/transfers").json()["cleanup"]
        if cleanup and cleanup[0]["state"] == "error":
            break
        time.sleep(0.03)
    assert cleanup[0]["state"] == "error"
    assert "sensitive-detail" not in cleanup[0]["error"]
    config = client.get("/api/storage").json()[0]
    assert client.delete(f"/api/storage/{config['id']}").status_code == 409
    storage.delete = original
    assert client.post("/api/cleanup/retry").status_code == 200
    for _ in range(100):
        if not client.get("/api/transfers").json()["cleanup"]:
            break
        time.sleep(0.03)
    assert not client.get("/api/transfers").json()["cleanup"]


def test_full_application_restart(tmp_path):
    from fastapi.testclient import TestClient
    from conftest import FakeStorage
    from app.common.config import Settings
    from app.common.security import new_id, passwords
    from app.main import create_app

    settings = Settings(data_dir=tmp_path, block_size=8192, chunk_size=4096, temp_limit=32768)
    storage = FakeStorage()
    application = create_app(settings, storage)
    with TestClient(application) as client:
        application.state.db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?)",
            (new_id(), "admin", passwords.hash("restart-password"), 1, 0, time.time()),
        )
        login = client.post(
            "/api/auth/login", json={"username": "admin", "password": "restart-password"}
        ).json()
        client.headers["X-CSRF-Token"] = login["csrf"]
        client.post(
            "/api/storage", json={"name": "bot", "token": "123456:" + 32 * "x", "channel": "-1001234567890"}
        )
        data = b"persisted-data" * 1100
        body = {"name": "restart.bin", "size": len(data), "fingerprint": hashlib.sha256(data).hexdigest()}
        task = client.post("/api/uploads", json=body).json()
        chunk = data[:4096]
        client.put(
            f"/api/uploads/{task['id']}/chunks?offset=0",
            content=chunk,
            headers={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()},
        )
        cookies = dict(client.cookies)
    with TestClient(create_app(settings, storage)) as client:
        client.cookies.update(cookies)
        client.headers["X-CSRF-Token"] = login["csrf"]
        resumed = client.post("/api/uploads", json=body).json()
        assert resumed["id"] == task["id"] and resumed["received"] == 4096
        for offset in range(4096, len(data), 4096):
            chunk = data[offset : offset + 4096]
            response = client.put(
                f"/api/uploads/{task['id']}/chunks?offset={offset}",
                content=chunk,
                headers={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()},
            )
            assert response.status_code == 200, response.text
        wait_for(client, task["id"], "complete")
        assert client.get(f"/api/files/{task['node_id']}/download").content == data


def test_drive_upload_download_and_purge_through_bot_api(setup):
    import email.policy
    from email.parser import BytesParser
    import json
    import httpx
    from app.storage.telegram import TelegramStorage

    client, app, _ = setup
    messages = {}
    next_id = 0

    async def handler(request):
        nonlocal next_id
        method = request.url.path.rsplit("/", 1)[-1]
        body = await request.aread()
        if method == "sendDocument":
            parser = BytesParser(policy=email.policy.default)
            multipart = parser.parsebytes(
                b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + body
            )
            document = next(
                part
                for part in multipart.iter_parts()
                if part.get_param("name", header="content-disposition") == "document"
            )
            next_id += 1
            messages[next_id] = document.get_payload(decode=True)
            result = {"message_id": next_id, "document": {"file_id": f"file-{next_id}"}}
        elif method == "getFile":
            file_id = json.loads(body)["file_id"]
            result = {"file_path": f"documents/{file_id}.bin"}
        elif method == "deleteMessage":
            messages.pop(json.loads(body)["message_id"])
            result = True
        else:
            identity = int(method.removeprefix("file-").removesuffix(".bin"))
            return httpx.Response(200, content=messages[identity])
        return httpx.Response(200, json={"ok": True, "result": result})

    app.state.storage = TelegramStorage(app.state.settings, app.state.secrets, httpx.MockTransport(handler))
    data = bytes(range(256)) * 90
    task = upload_file(client, data, "cloud-api.bin")
    wait_for(client, task["id"], "complete")
    assert client.get(f"/api/files/{task['node_id']}/download").content == data
    response = client.get(f"/api/files/{task['node_id']}/download", headers={"Range": "bytes=7000-19000"})
    assert response.status_code == 206 and response.content == data[7000:19001]
    blocks = app.state.db.all("SELECT * FROM blocks WHERE upload_id=?", (task["id"],))
    assert len(blocks) == 3 and all(b["file_id"] and b["message_id"] for b in blocks)
    client.post("/api/files/batch", json={"ids": [task["node_id"]], "action": "trash"})
    client.post("/api/files/batch", json={"ids": [task["node_id"]], "action": "purge"})
    for _ in range(150):
        if not messages:
            break
        time.sleep(0.03)
    assert not messages
