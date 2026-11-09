import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_drive import upload_file, wait_for

from app.common.security import digest
from app.shares.service import COOKIE


def ready(client, name="shared.mp4", parent=None):
    data = bytes(range(256)) * 95
    task = upload_file(client, data, name, parent)
    wait_for(client, task["id"], "complete")
    return task, data


def create(client, task, **options):
    result = client.post("/api/shares", json={"node_id": task["node_id"], **options})
    assert result.status_code == 201, result.text
    return result.json()


def public_path(share):
    return "/api/public/shares/" + share["path"].rsplit("/", 1)[-1]


@pytest.mark.parametrize(
    "title,expected", [(None, "好东西"), ("", "好东西"), ("   ", "好东西"), ("  分享视频  ", "分享视频")]
)
def test_public_share_titles_metadata_and_media(setup, title, expected):
    client, app, storage = setup
    task, data = ready(client)
    share = create(client, task, **({"title": title} if title is not None else {}))
    assert share["title"] == expected
    guest = TestClient(app)
    path = public_path(share)
    info = guest.get(path).json()
    assert info["title"] == expected and not info["requires_password"] and info["preview_kind"] == "video"
    assert "owner_id" not in info and "token_cipher" not in info
    response = guest.get(path + "/preview", headers={"Range": "bytes=7500-19000"})
    assert response.status_code == 206 and response.content == data[7500:19001]
    assert response.headers["content-type"] == "video/mp4"
    assert guest.get(path + "/download").content == data
    assert guest.head(path + "/preview").headers["accept-ranges"] == "bytes"
    assert guest.get(share["path"]).headers["referrer-policy"] == "no-referrer"
    assert "noindex" in guest.get(share["path"]).headers["x-robots-tag"]
    assert guest.get("/api/files").status_code == 401
    assert client.get("/api/shares").json()[0]["title"] == expected
    guest.close()


def test_password_grant_cookie_blocks_direct_range_and_is_share_specific(setup):
    client, app, storage = setup
    task, data = ready(client, "secret.png")
    expiry = datetime.now(UTC) + timedelta(hours=1)
    share = create(client, task, password="correct-password", expires_at=expiry.isoformat(), title="图片分享")
    path = public_path(share)
    guest = TestClient(app)
    assert guest.get(path).json() == {"requires_password": True, "title": "图片分享"}
    for endpoint in ("/download", "/preview"):
        assert guest.get(path + endpoint, headers={"Range": "bytes=0-100"}).status_code == 403
        assert guest.head(path + endpoint).status_code == 403
    assert guest.post(path + "/unlock", json={"password": "wrong"}).status_code == 403
    unlocked = guest.post(path + "/unlock", json={"password": "correct-password"})
    assert unlocked.status_code == 200 and unlocked.json()["name"] == "secret.png"
    cookie = unlocked.headers["set-cookie"]
    assert "HttpOnly" in cookie and f"Path={path}" in cookie and "SameSite=lax" in cookie
    value = guest.cookies.get(COOKIE)
    session = app.state.db.one("SELECT * FROM share_sessions WHERE token_hash=%s", (digest(value),))
    assert session["expires_at"] <= expiry.timestamp() and session["share_id"] == share["id"]
    assert guest.get(path + "/preview", headers={"Range": "bytes=-100"}).content == data[-100:]
    assert guest.get(path + "/download").content == data
    other = create(client, task, password="correct-password")
    assert (
        guest.get(public_path(other) + "/download", headers={"Cookie": f"{COOKIE}={value}"}).status_code
        == 403
    )
    row = app.state.db.one("SELECT * FROM shares WHERE id=%s", (share["id"],))
    assert row["password"] != "correct-password" and row["token_cipher"] != share["path"].rsplit("/", 1)[-1]
    assert "password" not in client.get("/api/shares").json()[0]
    assert (
        guest.post(
            path + "/unlock",
            json={"password": "correct-password"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    guest.close()


def test_logged_in_owner_can_unlock_without_private_csrf_token(setup):
    client, app, storage = setup
    task, data = ready(client)
    share = create(client, task, password="secret-code")
    headers = client.headers.pop("x-csrf-token")
    assert client.post(public_path(share) + "/unlock", json={"password": "secret-code"}).status_code == 200
    assert client.post("/api/shares", json={"node_id": task["node_id"]}).status_code == 403
    client.headers["x-csrf-token"] = headers


def test_expiration_revocation_and_expired_grant_are_enforced(setup):
    client, app, storage = setup
    task, data = ready(client)
    guest = TestClient(app)
    for mode in ("expiry", "revoke", "grant"):
        share = create(client, task, password="test-secret")
        path = public_path(share)
        assert guest.post(path + "/unlock", json={"password": "test-secret"}).status_code == 200
        assert guest.get(path + "/preview", headers={"Range": "bytes=0-99"}).status_code == 206
        if mode == "expiry":
            app.state.db.execute("UPDATE shares SET expires_at=%s WHERE id=%s", (time.time() - 1, share["id"]))
        elif mode == "revoke":
            assert client.delete("/api/shares/" + share["id"]).status_code == 200
        else:
            app.state.db.execute(
                "UPDATE share_sessions SET expires_at=%s WHERE share_id=%s", (time.time() - 1, share["id"])
            )
        expected = 403 if mode == "grant" else 404
        for endpoint in ("/preview", "/download"):
            assert guest.get(path + endpoint, headers={"Range": "bytes=9000-12000"}).status_code == expected
            assert guest.head(path + endpoint).status_code == expected
        if mode != "grant":
            assert guest.get(path).status_code == 404
    guest.close()


def test_trash_revokes_nested_file_shares_and_restore_does_not_reactivate(setup):
    client, app, storage = setup
    folder = client.post("/api/files/folders", json={"name": "folder"}).json()
    task, data = ready(client, parent=folder["id"])
    share = create(client, task)
    guest = TestClient(app)
    assert guest.get(public_path(share) + "/download").status_code == 200
    assert client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "trash"}).status_code == 200
    assert guest.get(public_path(share)).status_code == 404
    assert (
        client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "restore"}).status_code == 200
    )
    assert guest.get(public_path(share)).status_code == 404
    fresh = create(client, task)
    client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "trash"})
    assert client.post("/api/files/batch", json={"ids": [folder["id"]], "action": "purge"}).status_code == 200
    assert not app.state.db.one("SELECT id FROM shares WHERE id=%s", (fresh["id"],))
    guest.close()


def test_shares_are_owner_isolated_and_disabled_accounts_block_access(setup):
    client, app, storage = setup
    task, data = ready(client)
    share = create(client, task)
    other = client.post("/api/users", json={"username": "other", "password": "other-password"}).json()
    guest = TestClient(app)
    result = guest.post("/api/auth/login", json={"username": "other", "password": "other-password"}).json()
    guest.headers["X-CSRF-Token"] = result["csrf"]
    assert guest.get("/api/shares").json() == []
    assert guest.delete("/api/shares/" + share["id"]).status_code == 404
    assert guest.post("/api/shares", json={"node_id": task["node_id"]}).status_code == 404
    owner = app.state.db.one("SELECT owner_id FROM shares WHERE id=%s", (share["id"],))["owner_id"]
    assert owner != other["id"]
    app.state.db.execute("UPDATE users SET disabled=1 WHERE id=%s", (owner,))
    assert guest.get(public_path(share)).status_code == 404
    guest.close()


def test_password_attempts_are_rate_limited(setup):
    client, app, storage = setup
    task, _ = ready(client)
    share = create(client, task, password="correct-code")
    guest = TestClient(app)
    for _ in range(10):
        assert guest.post(public_path(share) + "/unlock", json={"password": "wrong"}).status_code == 403
    assert guest.post(public_path(share) + "/unlock", json={"password": "correct-code"}).status_code == 429
    guest.close()


def test_invalid_share_targets_and_expiry(setup):
    client, app, storage = setup
    pending = client.post("/api/uploads", json={"name": "pending", "size": 1, "fingerprint": "a" * 64}).json()
    assert client.post("/api/shares", json={"node_id": pending["node_id"]}).status_code == 409
    task, _ = ready(client)
    assert (
        client.post(
            "/api/shares",
            json={
                "node_id": task["node_id"],
                "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            },
        ).status_code
        == 422
    )
    assert client.post("/api/shares", json={"node_id": task["node_id"], "password": "abc"}).status_code == 422
    assert (
        client.post("/api/shares", json={"node_id": task["node_id"], "title": "x" * 201}).status_code == 422
    )
    assert client.get("/api/public/shares/not-a-share").status_code == 404


def test_expiration_stops_an_already_open_shared_stream(setup):
    import asyncio

    from fastapi import HTTPException, Request

    from app.shares.routes import shared_file

    client, app, storage = setup
    task, _ = ready(client)
    share = create(client, task)
    token = share["path"].rsplit("/", 1)[-1]
    original = storage.download

    async def small_chunks(*args):
        async for data in original(*args):
            for offset in range(0, len(data), 64):
                yield data[offset : offset + 64]

    storage.download = small_chunks

    async def receive():
        await asyncio.sleep(3600)

    request = Request(
        {"type": "http", "method": "GET", "path": public_path(share) + "/preview", "headers": [], "app": app},
        receive,
    )

    async def run():
        response = await shared_file(token, request, inline=True)
        body = response.body_iterator
        assert len(await anext(body)) == 64
        app.state.db.execute("UPDATE shares SET expires_at=%s WHERE id=%s", (time.time() - 1, share["id"]))
        await asyncio.sleep(1.05)
        with pytest.raises(HTTPException) as error:
            await anext(body)
        assert error.value.status_code == 404
        await body.aclose()
        assert not app.state.active_downloads and app.state.preview_slots._value == 2

    asyncio.run(run())
