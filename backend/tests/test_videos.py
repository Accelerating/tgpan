import asyncio
import json
import time
from pathlib import Path

import pytest

from app.common.security import new_id, passwords
from app.offline.service import task_directory
from app.videos.cookies import cookie_file, normalize_cookie


def wait_task(client, identity, states):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        task = next(row for row in client.get("/api/videos").json() if row["id"] == identity)
        if task["state"] in states:
            return task
        time.sleep(0.06)
    raise AssertionError(task)


@pytest.fixture
def video(setup, monkeypatch):
    client, app, storage = setup
    for name in ("yt-dlp", "ffmpeg"):
        monkeypatch.setattr(app.state.component_registry[name], "executable", lambda: "/fake/component")

    async def public(value):
        return value

    async def extract(state, owner, cookie, source, flat=True):
        if flat and "playlist" in source:
            return {
                "_type": "playlist",
                "title": "Collection",
                "entries": [
                    {"id": str(i), "title": f"Episode {i}", "url": f"https://example.org/video/{i}"}
                    for i in (1, 2)
                ],
            }
        return {
            "id": "one",
            "title": "Test video",
            "webpage_url": source,
            "duration": 120,
            "uploader": "Creator",
            "extractor": "test",
            "height": 1080,
            "ext": "mp4",
            "formats": [{"height": 1080}, {"height": 720}],
            "vcodec": "h264",
            "acodec": "aac",
            "description": "Description",
            "subtitles": {"en": [{"ext": "vtt", "url": "secret-url"}]},
        }

    async def run(state, owner, cookie, args, output=None, timeout=300):
        template = args[args.index("--output") + 1]
        Path(template.replace("%(ext)s", "m4a" if "--extract-audio" in args else "mp4")).write_bytes(
            b"v" * 21000
        )
        if output:
            await output('PROGRESS:{"downloaded_bytes":21000,"speed":200}\nPROCESS:finished\n')

    monkeypatch.setattr("app.videos.routes.public_url", public)
    monkeypatch.setattr("app.videos.service.extract", extract)
    monkeypatch.setattr("app.videos.service.run", run)
    return client, app, storage


def create(client, source="https://example.org/video", **kwargs):
    response = client.post("/api/videos", json={"sources": [source], **kwargs})
    assert response.status_code == 201, response.text
    return wait_task(client, response.json()[0], {"selecting", "error"})


def start(client, task, positions=None, **kwargs):
    response = client.post(
        f"/api/videos/{task['id']}/select",
        json={"positions": positions or [e["position"] for e in task["entries"]], **kwargs},
    )
    assert response.status_code == 200, response.text
    return wait_task(client, task["id"], {"complete", "error"})


def test_video_import_metadata_and_task_deletion(video):
    client, app, storage = video
    task = create(client)
    assert task["entries"][0]["metadata"]["qualities"] == [1080, 720]
    assert client.get("/api/offline").json() == []
    assert "source" not in task and "source" not in task["entries"][0]
    task = start(client, task, quality="720")
    assert task["state"] == "complete", task
    assert task["stored"] == task["total"] == 21000
    assert not task_directory(app.state, task["id"]).exists()
    node = client.get("/api/files").json()["items"][0]
    assert node["has_video_metadata"] and node["status"] == "ready"
    assert client.get(f"/api/files/{node['id']}/download").content == b"v" * 21000
    assert len(storage.messages) == 3
    assert client.get("/api/transfers").json()["uploads"] == []
    assert app.state.db.one("SELECT origin FROM uploads")["origin"] == "video"
    metadata = client.get(f"/api/videos/files/{node['id']}").json()
    assert metadata["uploader"] == "Creator" and "secret-url" not in json.dumps(metadata)
    assert client.delete(f"/api/videos/{task['id']}").status_code == 200
    assert client.get(f"/api/videos/files/{node['id']}").json() == metadata


def test_playlist_selection_and_audio(video):
    client, app, _ = video
    result = start(client, create(client, "https://example.org/playlist"), [2], audio_only=True)
    assert result["state"] == "complete", result
    assert app.state.db.all("SELECT name FROM nodes WHERE kind='file'") == [{"name": "002 - Episode 2.m4a"}]
    assert app.state.db.one("SELECT name FROM nodes WHERE kind='folder'")["name"] == "Collection"


def test_cookie_encryption_scoping_update_and_delete(video):
    client, app, _ = video
    payload = {"name": "Login", "domain": "example.org", "value": "session=secret-value; key=two"}
    response = client.post("/api/videos/cookies", json=payload)
    assert response.status_code == 201
    identity = response.json()["id"]
    assert "secret-value" not in json.dumps(client.get("/api/videos/cookies").json())
    assert "secret-value" not in app.state.db.one("SELECT secret FROM video_cookies")["secret"]
    owner = app.state.db.one("SELECT id FROM users")["id"]
    with cookie_file(app.state, owner, identity) as path:
        assert path.stat().st_mode & 0o777 == 0o600
        assert ".example.org\tTRUE\t/\tTRUE\t0\tsession\tsecret-value" in path.read_text()
    assert not path.exists()
    assert (
        client.post(
            "/api/videos", json={"sources": ["https://other.org/v"], "cookie_id": identity}
        ).status_code
        == 422
    )
    task = create(client, cookie_id=identity)
    assert client.delete(f"/api/videos/cookies/{identity}").status_code == 409
    assert (
        client.put(f"/api/videos/cookies/{identity}", json=payload | {"value": "session=new"}).status_code
        == 200
    )
    assert client.post(f"/api/videos/{task['id']}/cancel").status_code == 200
    assert client.delete(f"/api/videos/cookies/{identity}").status_code == 200
    with pytest.raises(Exception):
        normalize_cookie(".other.org\tTRUE\t/\tTRUE\t0\tx\ty", "example.org")


def test_storage_retry_reuses_upload(video):
    client, app, storage = video
    storage.fail = True
    task = start(client, create(client))
    assert task["state"] == "error" and task["phase"] == "store"
    upload = app.state.db.one("SELECT id FROM uploads")["id"]
    storage.fail = False
    assert client.post(f"/api/videos/{task['id']}/retry").status_code == 200
    result = wait_task(client, task["id"], {"complete", "error"})
    assert result["state"] == "complete", result
    assert app.state.db.one("SELECT id FROM uploads")["id"] == upload


def test_video_permissions(video):
    client, app, _ = video
    task = create(client)
    cookie = client.post(
        "/api/videos/cookies", json={"name": "Login", "domain": "example.org", "value": "s=secret"}
    ).json()["id"]
    app.state.db.execute(
        "INSERT INTO users VALUES (%s,%s,%s,0,0,%s)",
        (new_id(), "other", passwords.hash("test-password-123"), time.time()),
    )
    login = client.post("/api/auth/login", json={"username": "other", "password": "test-password-123"}).json()
    client.headers["X-CSRF-Token"] = login["csrf"]
    assert client.get("/api/videos").json() == [] and client.get("/api/videos/cookies").json() == []
    assert client.delete(f"/api/videos/cookies/{cookie}").status_code == 404
    assert client.post(f"/api/videos/{task['id']}/cancel").status_code == 404
    assert client.post("/api/components/yt-dlp/install").status_code == 403
    assert client.post("/api/components/ffmpeg/install").status_code == 403


def test_size_guard_and_cancel(video):
    client, app, _ = video
    app.state.settings.max_file_size = 100
    task = start(client, create(client))
    assert task["state"] == "error" and "大小超出限制" in task["error"]
    assert app.state.db.all("SELECT id FROM uploads") == []
    assert client.post(f"/api/videos/{task['id']}/cancel").status_code == 200
    assert not task_directory(app.state, task["id"]).exists()


def test_pause_resume_cancel_transfer(video):
    client, app, storage = video
    storage.blocked = True
    task = create(client)
    client.post(f"/api/videos/{task['id']}/select", json={"positions": [1]})
    wait_task(client, task["id"], {"storing"})
    assert client.post(f"/api/videos/{task['id']}/pause").status_code == 200
    assert task_directory(app.state, task["id"]).exists()
    assert client.post(f"/api/videos/{task['id']}/resume").status_code == 200
    wait_task(client, task["id"], {"storing"})
    assert client.post(f"/api/videos/{task['id']}/cancel").status_code == 200
    storage.blocked = False
    assert client.get("/api/files").json()["items"] == []


def test_cli_jar_cleanup_on_failure(video, monkeypatch):
    client, app, _ = video
    identity = client.post(
        "/api/videos/cookies", json={"name": "Login", "domain": "example.org", "value": "s=private-secret"}
    ).json()["id"]
    owner = app.state.db.one("SELECT id FROM users")["id"]
    observed = []

    async def command(args, **kwargs):
        jar = Path(args[args.index("--cookies") + 1])
        observed.append(jar)
        assert jar.is_file() and "private-secret" in jar.read_text()
        assert "--ignore-config" in args and "--no-plugin-dirs" in args and "--proxy" in args
        assert not any("private-secret" in str(arg) for arg in args)
        raise TimeoutError()

    monkeypatch.setattr("app.videos.engine.command", command)
    from app.videos.engine import run

    with pytest.raises(TimeoutError):
        asyncio.run(run(app.state, owner, identity, ["--", "https://example.org/v"]))
    assert not observed[-1].exists()


def test_real_ytdlp_ffmpeg_download(setup, monkeypatch, tmp_path):
    """Run real CLI tools against a tiny local video; only the fixture DNS is overridden."""
    import functools
    import shutil
    import socket
    import subprocess
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from app.offline import network, proxy

    if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
        pytest.skip("yt-dlp and ffmpeg are required for the real CLI integration")
    source = tmp_path / "clip.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=0.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=tmp_path)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = network.public_addresses

    async def addresses(host, port):
        if host == "video-fixture.test":
            return await asyncio.get_running_loop().getaddrinfo("127.0.0.1", port, type=socket.SOCK_STREAM)
        return await original(host, port)

    monkeypatch.setattr(network, "public_addresses", addresses)
    monkeypatch.setattr(proxy, "public_addresses", addresses)
    client, app, _ = setup
    try:
        task = create(client, f"http://video-fixture.test:{server.server_port}/clip.mp4")
        assert task["state"] == "selecting", task
        task = start(client, task)
        assert task["state"] == "complete", task
        node = client.get("/api/files").json()["items"][0]
        assert client.get(f"/api/files/{node['id']}/download").content == source.read_bytes()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("paused", [False, True])
def test_worker_restart_preserves_video_upload_and_pause(video, paused):
    from app.offline.service import OfflineWorker
    from app.transfers.service import Worker

    client, app, storage = video
    storage.blocked = True
    task = create(client)
    client.post(f"/api/videos/{task['id']}/select", json={"positions": [1]})
    wait_task(client, task["id"], {"storing"})
    deadline = time.monotonic() + 5
    while not app.state.db.one("SELECT id FROM uploads") and time.monotonic() < deadline:
        time.sleep(0.02)
    upload = app.state.db.one("SELECT id FROM uploads")["id"]
    if paused:
        assert client.post(f"/api/videos/{task['id']}/pause").status_code == 200

    async def restart():
        await app.state.offline.stop()
        await app.state.worker.stop()
        app.state.worker = Worker(app.state)
        app.state.offline = OfflineWorker(app.state)
        await app.state.worker.start()
        await app.state.offline.start()

    client.portal.call(restart)
    if paused:
        assert wait_task(client, task["id"], {"paused"})["state"] == "paused"
        assert client.post(f"/api/videos/{task['id']}/resume").status_code == 200
    storage.blocked = False
    result = wait_task(client, task["id"], {"complete", "error"})
    assert result["state"] == "complete", result
    assert app.state.db.all("SELECT id FROM uploads") == [{"id": upload}]
    assert app.state.db.one("SELECT node_id FROM video_entries")["node_id"]


def test_httponly_cookie_domains_are_validated(video):
    from fastapi import HTTPException

    client, _, _ = video
    with pytest.raises(HTTPException):
        normalize_cookie("#HttpOnly_.other.org\tTRUE\t/\tTRUE\t0\ts\tsecret", "example.org")
    response = client.post(
        "/api/videos/cookies",
        json={
            "name": "HTTPOnly",
            "domain": "example.org",
            "value": "# Netscape HTTP Cookie File\n#HttpOnly_.example.org\tTRUE\t/\tTRUE\t0\ts\tsecret",
        },
    )
    assert response.status_code == 201, response.text


def test_stale_cookie_jars_are_removed(tmp_path):
    from types import SimpleNamespace

    from app.videos.cookies import cleanup_cookie_files

    private = tmp_path / 'video-cookie-crashed'
    private.mkdir()
    (private / 'cookies.txt').write_text('s=secret')
    unrelated = tmp_path / 'other-data'
    unrelated.mkdir()
    cleanup_cookie_files(SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path)))
    assert not private.exists() and unrelated.exists()
