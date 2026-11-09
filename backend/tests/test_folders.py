import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from test_moves import folder
from test_shares import create, public_path, ready

from app.shares.routes import shared_file


@contextmanager
def guest_client(app):
    guest = TestClient(app)
    try:
        yield guest
    finally:
        guest.close()


def resolve(client, paths, parent=None):
    return client.post("/api/files/folders/resolve", json={"paths": paths, "parent_id": parent})


def test_folder_upload_hierarchy_reuse_and_file_transfer(setup):
    client, app, storage = setup
    destination = folder(client, "destination")
    paths = ["photos/2026/events", "photos/empty", "photos/2026", "photos"]
    response = resolve(client, paths, destination["id"])
    assert response.status_code == 200, response.text
    ids = response.json()
    assert resolve(client, paths, destination["id"]).json() == ids
    assert len(app.state.db.all("SELECT id FROM nodes")) == 5
    assert (
        app.state.db.one("SELECT parent_id FROM nodes WHERE id=%s", (ids["photos/2026/events"],))["parent_id"]
        == ids["photos/2026"]
    )
    task, content = ready(client, "image.png", ids["photos/2026/events"])
    assert client.get(f"/api/files/{task['node_id']}/download").content == content
    assert client.get("/api/files", params={"parent_id": ids["photos/empty"]}).json()["items"] == []
    normalized = resolve(client, [" cafe\u0301 /child", "café/child"]).json()
    assert normalized[" cafe\u0301 /child"] == normalized["café/child"]


@pytest.mark.parametrize(
    "path", ["../escape", "/root", "root/", "root//child", "root/./child", "a\\b", "a/\x00"]
)
def test_invalid_upload_paths_create_no_folders(setup, path):
    client, app, _ = setup
    assert resolve(client, ["valid/first", path]).status_code == 422
    assert app.state.db.all("SELECT id FROM nodes") == []


def test_folder_upload_conflict_rolls_back_and_enforces_ownership(setup):
    client, app, _ = setup
    task, _ = ready(client, "occupied")
    assert resolve(client, ["new/child", "occupied/child"]).status_code == 409
    assert app.state.db.all("SELECT id FROM nodes WHERE kind='folder'") == []
    assert resolve(client, ["child"], task["node_id"]).status_code == 400
    parent = folder(client, "private")
    client.post("/api/files/batch", json={"ids": [parent["id"]], "action": "trash"})
    assert resolve(client, ["child"], parent["id"]).status_code == 404
    assert resolve(client, ["/".join(["a"] * 101)]).status_code == 422
    other = client.post("/api/users", json={"username": "other", "password": "other-password"}).json()
    app.state.db.execute("UPDATE nodes SET owner_id=%s WHERE id=%s", (other["id"], parent["id"]))
    assert resolve(client, ["child"], parent["id"]).status_code == 404


def test_folder_share_password_browsing_ranges_and_scope(setup):
    client, app, _ = setup
    outer = folder(client, "private ancestor")
    root = folder(client, "shared", outer["id"])
    child = folder(client, "nested", root["id"])
    empty = folder(client, "empty", root["id"])
    task, data = ready(client, "video.mp4", child["id"])
    outside, _ = ready(client, "outside.png")
    pending = client.post(
        "/api/uploads",
        json={
            "name": "pending",
            "size": 1,
            "fingerprint": "a" * 64,
            "parent_id": root["id"],
        },
    ).json()
    share = create(client, {"node_id": root["id"]}, password="secret-code")
    path = public_path(share)
    with guest_client(app) as guest:
        assert guest.get(path).json() == {"title": "好东西", "requires_password": True}
        assert guest.get(path + "/files").status_code == 403
        assert guest.head(f"{path}/files/{task['node_id']}/preview").status_code == 403
        assert guest.post(path + "/unlock", json={"password": "secret-code"}).json()["kind"] == "folder"
        listing = guest.get(path + "/files").json()
        assert [n["id"] for n in listing["items"]] == [child["id"]]
        assert listing["breadcrumbs"] == [{"id": root["id"], "name": root["name"]}]
        assert "owner_id" not in listing["items"][0]
        assert guest.get(path + "/files", params={"parent_id": empty["id"]}).status_code == 404
        nested = guest.get(path + "/files", params={"parent_id": child["id"]}).json()
        assert len(nested["breadcrumbs"]) == 2
        assert nested["items"][0]["preview_kind"] == "video"
        endpoint = f"{path}/files/{task['node_id']}"
        assert (
            guest.get(endpoint + "/preview", headers={"Range": "bytes=7500-19000"}).content
            == data[7500:19001]
        )
        assert guest.head(endpoint + "/download").headers["content-length"] == str(len(data))
        for identity in (outside["node_id"], pending["node_id"], outer["id"]):
            for action in ("download", "preview"):
                assert guest.get(f"{path}/files/{identity}/{action}").status_code == 404
                assert guest.head(f"{path}/files/{identity}/{action}").status_code == 404
            assert guest.get(path + "/files", params={"parent_id": identity}).status_code == 404
        # Moving a complete subtree out removes access; moving it back restores membership.
        for parent, expected in ((None, 404), (root["id"], 200)):
            assert client.patch(f"/api/files/{child['id']}", json={"parent_id": parent}).status_code == 200
            assert guest.get(endpoint + "/download").status_code == expected
        assert client.delete(f"/api/shares/{share['id']}").status_code == 200
        assert guest.get(endpoint + "/download").status_code == 404
        assert guest.get(path + "/files").status_code == 404


@pytest.mark.parametrize("mode", ["trash", "expire", "disable"])
def test_folder_share_invalidation(setup, mode):
    client, app, _ = setup
    root = folder(client, "shared")
    task, _ = ready(client, parent=root["id"])
    share = create(
        client, {"node_id": root["id"]}, expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    path = public_path(share)
    assert client.get(path + "/files").status_code == 200
    if mode == "trash":
        client.post("/api/files/batch", json={"ids": [root["id"]], "action": "trash"})
        client.post("/api/files/batch", json={"ids": [root["id"]], "action": "restore"})
    elif mode == "expire":
        app.state.db.execute("UPDATE shares SET expires_at=0 WHERE id=%s", (share["id"],))
    else:
        app.state.db.execute("UPDATE users SET disabled=1")
    with guest_client(app) as guest:
        assert guest.get(path + "/files").status_code == 404
        assert guest.head(f"{path}/files/{task['node_id']}/preview").status_code == 404


def test_moving_file_out_interrupts_shared_stream(setup):
    client, app, storage = setup
    root = folder(client, "shared")
    task, _ = ready(client, parent=root["id"])
    share = create(client, {"node_id": root["id"]})
    token = share["path"].rsplit("/", 1)[-1]

    async def receive():
        await asyncio.sleep(3600)

    request = Request(
        {"type": "http", "method": "GET", "path": public_path(share), "headers": [], "app": app}, receive
    )

    async def run():
        response = await shared_file(token, request, node_id=task["node_id"])
        iterator = response.body_iterator
        await anext(iterator)
        app.state.db.execute("UPDATE nodes SET parent_id=NULL WHERE id=%s", (task["node_id"],))
        await asyncio.sleep(1.05)
        with pytest.raises(HTTPException) as error:
            await anext(iterator)
        assert error.value.status_code == 404
        await iterator.aclose()
        assert not app.state.active_downloads

    client.portal.call(run)


def test_empty_folders_cannot_be_shared_or_downloaded(setup):
    client, app, _ = setup
    root = folder(client, "empty")
    child = folder(client, "nested empty", root["id"])
    for node in (root, child):
        response = client.post("/api/shares", json={"node_id": node["id"]})
        assert response.status_code == 409
        assert "没有已完成的文件" in response.json()["detail"]
        assert client.get(f"/api/files/{node['id']}/download").status_code == 409
    task = client.post(
        "/api/uploads",
        json={
            "name": "pending.txt",
            "size": 1,
            "fingerprint": "a" * 64,
            "parent_id": child["id"],
        },
    ).json()
    assert client.post("/api/shares", json={"node_id": root["id"]}).status_code == 409
    client.post(f"/api/uploads/{task['id']}/cancel")
    ready_task, _ = ready(client, parent=child["id"])
    share = create(client, {"node_id": root["id"]})
    path = public_path(share)
    assert client.get(path + "/files").status_code == 200
    client.post("/api/files/batch", json={"ids": [ready_task["node_id"]], "action": "trash"})
    assert client.get(path).status_code == 404
    assert client.get(path + "/files").status_code == 404
    assert client.head(path + "/download").status_code == 404
