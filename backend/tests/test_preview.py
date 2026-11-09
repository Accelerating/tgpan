from test_drive import upload_file, wait_for


def ready(client, data, name):
    task = upload_file(client, data, name)
    wait_for(client, task["id"], "complete")
    return task


def test_image_preview_headers_head_and_listing(setup):
    client, app, storage = setup
    content = b"\x89PNG\r\n\x1a\n" + b"image-content" * 1500
    task = ready(client, content, "图片.PNG")
    url = f"/api/files/{task['node_id']}/preview"
    response = client.get(url)
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"

    async def no_download(*args):
        raise AssertionError("HEAD must not download Telegram content")
        yield b""

    storage.download = no_download
    response = client.head(url)
    assert response.status_code == 200 and not response.content
    assert int(response.headers["content-length"]) == len(content)
    assert client.get("/api/files").json()["items"][0]["preview_kind"] == "image"
    assert not app.state.active_downloads


def test_video_seek_crosses_blocks_and_preserves_download(setup):
    client, app, storage = setup
    content = bytes(range(256)) * 100
    task = ready(client, content, "video.mp4")
    url = f"/api/files/{task['node_id']}/preview"
    for header, expected in [
        ("bytes=7001-19003", content[7001:19004]),
        ("bytes=-200", content[-200:]),
        ("bytes=24000-", content[24000:]),
    ]:
        response = client.get(url, headers={"Range": header})
        assert response.status_code == 206 and response.content == expected
        assert response.headers["content-type"] == "video/mp4"
        assert response.headers["accept-ranges"] == "bytes"
        assert int(response.headers["content-length"]) == len(expected)
    response = client.get(f"/api/files/{task['node_id']}/download")
    assert response.content == content and response.headers["content-disposition"].startswith("attachment;")
    assert client.get(url, headers={"Range": "bytes=999999-"}).status_code == 416
    assert client.get(url, headers={"Range": "bytes=0-1,4-5"}).status_code == 416
    assert not app.state.active_downloads and app.state.preview_slots._value == 2


def test_preview_caps_open_ranges_without_capping_download(setup):
    client, app, storage = setup
    task = ready(client, b"x", "big.webm")
    data = b"x" * (5 * 1024**2 + 17)
    block = app.state.db.one("SELECT * FROM blocks WHERE upload_id=%s", (task["id"],))
    storage.messages[int(block["file_id"])] = data
    app.state.db.execute("UPDATE blocks SET size=%s WHERE id=%s", (len(data), block["id"]))
    app.state.db.execute("UPDATE nodes SET size=%s WHERE id=%s", (len(data), task["node_id"]))
    response = client.get(f"/api/files/{task['node_id']}/preview", headers={"Range": "bytes=0-"})
    assert response.status_code == 206 and len(response.content) == 4 * 1024**2
    assert response.headers["content-range"] == f"bytes 0-{4 * 1024**2 - 1}/{len(data)}"
    response = client.get(f"/api/files/{task['node_id']}/preview", headers={"Range": f"bytes={4 * 1024**2}-"})
    assert response.content == data[4 * 1024**2 :]
    assert len(client.get(f"/api/files/{task['node_id']}/download").content) == len(data)


def test_preview_ownership_trash_and_unsupported_types(setup):
    client, app, storage = setup
    for name in ("page.html", "image.svg", "archive.zip"):
        task = ready(client, b"<script>bad()</script>", name)
        assert client.get(f"/api/files/{task['node_id']}/preview").status_code == 415
        assert client.get(f"/api/files/{task['node_id']}/download").status_code == 200
    task = ready(client, b"image", "private.jpg")
    url = f"/api/files/{task['node_id']}/preview"
    cookies = dict(client.cookies)
    client.cookies.clear()
    assert client.get(url).status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
    client.cookies.clear()
    client.cookies.update(cookies)
    client.post("/api/files/batch", json={"ids": [task["node_id"]], "action": "trash"})
    assert client.get(url).status_code == 404
    user = client.post("/api/users", json={"username": "viewer", "password": "viewer-password"}).json()
    owner = app.state.db.one("SELECT owner_id FROM nodes WHERE id=%s", (task["node_id"],))["owner_id"]
    assert user["id"] != owner
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": "viewer", "password": "viewer-password"})
    assert client.get(url).status_code == 404


def test_preview_remote_error_releases_slot(setup):
    client, app, storage = setup
    task = ready(client, b"image", "broken.jpg")

    async def failure(*args):
        raise ConnectionError("do-not-leak-bot-token")
        yield b""

    storage.download = failure
    response = client.get(f"/api/files/{task['node_id']}/preview")
    assert response.status_code == 502 and "do-not-leak" not in response.text
    assert not app.state.active_downloads and app.state.preview_slots._value == 2
