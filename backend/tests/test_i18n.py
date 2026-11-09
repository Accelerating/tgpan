import time

import pytest
from starlette.requests import Request

from app.common.i18n import detect_locale, translate
from app.storage.service import StorageTestFailure, TelegramError


@pytest.mark.parametrize(
    "header,expected",
    [
        ("", "en"),
        ("fr-FR, ja-JP", "en"),
        ("en-GB,zh-CN;q=0.8", "en"),
        ("zh-CN,en;q=0.9", "zh-CN"),
        ("zh-Hant-TW", "zh-CN"),
        ("ZH_hk", "zh-CN"),
        ("fr,zh;q=0.7", "zh-CN"),
        ("en;q=0.2,zh;q=0.9", "zh-CN"),
        ("zh;q=0,en", "en"),
        ("zh;q=bad,en", "en"),
        ("zh;q=2,en", "en"),
        ("zh;q=NaN,en", "en"),
        ("zh;q=-1,en", "en"),
        ("*", "en"),
    ],
)
def test_language_negotiation(header, expected):
    assert detect_locale(header) == expected


@pytest.mark.parametrize(
    "language,expected",
    [
        ("zh-TW", "分享不存在或已失效"),
        ("en-US", "This share does not exist or is no longer available."),
        ("fr-FR", "This share does not exist or is no longer available."),
        ("", "This share does not exist or is no longer available."),
    ],
)
def test_http_errors_and_headers(setup, language, expected):
    client, _, _ = setup
    response = client.get("/api/public/shares/missing", headers={"Accept-Language": language})
    assert response.status_code == 404
    assert response.json()["detail"] == expected
    assert response.headers["Content-Language"] == detect_locale(language)
    assert "Accept-Language" in response.headers["Vary"]


def test_validation_security_and_error_headers(setup):
    client, _, _ = setup
    for language in ("zh-CN", "en"):
        headers = {"Accept-Language": language}
        response = client.post("/api/auth/login", json={}, headers=headers)
        assert response.status_code == 422
        assert response.json()["detail"] == (
            "输入内容不符合要求，请检查后重试"
            if language == "zh-CN"
            else "Invalid input. Please check your entries and try again."
        )
        response = client.post(
            "/api/auth/login", json={}, headers=headers | {"Origin": "https://untrusted.test"}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == (
            "请求来源不受信任" if language == "zh-CN" else "Untrusted request origin"
        )
        assert response.headers["Content-Language"] == language
    for _ in range(10):
        response = client.post(
            "/api/auth/login", json={"username": "missing", "password": "test-password-123"}
        )
    response = client.post(
        "/api/auth/login",
        json={"username": "missing", "password": "test-password-123"},
        headers={"Accept-Language": "en"},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "900"
    assert response.json()["detail"] == "Too many attempts. Please try again later."


def test_dynamic_messages_preserve_names():
    request = Request({"type": "http", "headers": [(b"accept-language", b"en")]})
    name = "照片{p0}」，请更改名称或选择其他目录\n.png"
    message = f"目标目录中已存在同名项目「{name}」，请更改名称或选择其他目录"
    assert (
        translate(message, request)
        == f"An item named “{name}” already exists in the destination. Rename it or choose another folder."
    )
    assert (
        translate(TelegramError(429, retry_after=37).detail, request)
        == "Telegram rate limit reached. Retry in 37 seconds."
    )


def test_stored_errors_are_translated_per_request_without_changing_data(setup):
    client, app, _ = setup
    config = client.get("/api/storage").json()[0]
    task = client.post("/api/uploads", json={"name": "我的文件", "size": 1, "fingerprint": "a" * 64}).json()
    message = "临时文件不完整，请取消后重新上传"
    app.state.db.execute("UPDATE uploads SET error=%s WHERE id=%s", (message, task["id"]))
    app.state.db.execute(
        "INSERT INTO cleanup VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            "cleanup-i18n",
            app.state.db.one("SELECT id FROM users")["id"],
            config["id"],
            99,
            "error",
            message,
            time.time(),
        ),
    )
    headers = {"Accept-Language": "en"}
    expected = "Temporary file is incomplete. Cancel and upload again."
    assert client.get(f"/api/uploads/{task['id']}", headers=headers).json()["error"] == expected
    data = client.get("/api/transfers", headers=headers).json()
    assert data["uploads"][0]["name"] == "我的文件"
    assert data["uploads"][0]["error"] == expected
    assert data["cleanup"][0]["error"] == expected
    assert app.state.db.one("SELECT error FROM uploads WHERE id=%s", (task["id"],))["error"] == message
    assert client.get(f"/api/uploads/{task['id']}").json()["error"] == message


def test_storage_diagnostics_translate_system_text_only(setup, monkeypatch):
    client, _, storage = setup
    config = client.get("/api/storage").json()[0]

    async def success(config):
        return [
            {"step": "频道访问与权限", "ok": True, "detail": "测试文件已发送"},
            {"step": "上传", "ok": True, "detail": "测试文件已发送"},
        ]

    monkeypatch.setattr(storage, "test", success)
    path = f"/api/storage/{config['id']}/test"
    data = client.post(path, headers={"Accept-Language": "en"}).json()
    assert data["steps"][0] == {
        "step": "Channel access and permissions",
        "ok": True,
        "detail": "测试文件已发送",
    }
    assert data["steps"][1] == {"step": "Upload", "ok": True, "detail": "Test file sent"}

    async def failure(config):
        raise StorageTestFailure([], TelegramError(429, retry_after=37))

    monkeypatch.setattr(storage, "test", failure)
    assert (
        client.post(path, headers={"Accept-Language": "en"}).json()["error"]
        == "Telegram rate limit reached. Retry in 37 seconds."
    )


def test_default_share_title_uses_creation_language_and_custom_titles_stay_unchanged(setup):
    client, _, _ = setup
    task = client.post("/api/uploads", json={"name": "照片.png", "size": 0, "fingerprint": "b" * 64}).json()
    for language, title, expected in [
        ("en", "", "Shared files"),
        ("zh-CN", "", "好东西"),
        ("en", "我的文件", "我的文件"),
    ]:
        share = client.post(
            "/api/shares",
            json={"node_id": task["node_id"], "title": title},
            headers={"Accept-Language": language},
        ).json()
        assert share["title"] == expected
        public = client.get(
            f"/api/public/shares/{share['path'].split('/')[-1]}", headers={"Accept-Language": "en"}
        ).json()
        assert public["title"] == expected
        assert public["name"] == "照片.png"
