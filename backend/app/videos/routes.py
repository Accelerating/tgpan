import json
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.common.dependencies import User
from app.common.i18n import translate_fields
from app.common.security import new_id
from app.files.service import check_parent
from app.offline.network import public_url
from app.offline.routes import control as offline_control
from app.offline.routes import remove as offline_remove
from app.offline.service import get_task
from app.storage.service import get_config
from app.videos.cookies import domain_name, get_cookie, normalize_cookie
from app.videos.records import public_video
from app.videos.service import select as select_entries

router = APIRouter(prefix="/api/videos", tags=["videos"])


class Cookie(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    domain: str = Field(min_length=1, max_length=253)
    value: str = Field(min_length=1, max_length=128 * 1024)


class Create(BaseModel):
    sources: list[str] = Field(min_length=1, max_length=20)
    cookie_id: str | None = None
    parent_id: str | None = None
    config_id: str | None = None


class Selection(BaseModel):
    positions: list[int] = Field(min_length=1, max_length=200)
    quality: Literal["best", "2160", "1440", "1080", "720", "480", "360"] = "best"
    audio_only: bool = False


def video_task(state, owner, identity):
    task = get_task(state, owner, identity)
    if task["kind"] != "video":
        raise HTTPException(404, "视频任务不存在")
    return task


@router.get("/cookies")
def cookies(request: Request, user: User):
    return request.app.state.db.all(
        "SELECT id,name,domain,created_at,updated_at FROM video_cookies WHERE owner_id=%s ORDER BY name",
        (user["id"],),
    )


@router.post("/cookies", status_code=201)
def add_cookie(body: Cookie, request: Request, user: User):
    return save_cookie(body, request, user)


@router.put("/cookies/{identity}")
def update_cookie(identity: str, body: Cookie, request: Request, user: User):
    get_cookie(request.app.state, user["id"], identity)
    return save_cookie(body, request, user, identity)


def save_cookie(body, request, user, identity=None):
    state = request.app.state
    domain = domain_name(body.domain)
    content = normalize_cookie(body.value, domain)
    secret = state.secrets.cipher.encrypt(content.encode()).decode()
    now = time.time()
    if not body.name.strip():
        raise HTTPException(422, "请输入配置名称")
    if identity:
        state.db.execute(
            "UPDATE video_cookies SET name=%s,domain=%s,secret=%s,updated_at=%s WHERE id=%s",
            (body.name.strip(), domain, secret, now, identity),
        )
    else:
        identity = new_id()
        state.db.execute(
            "INSERT INTO video_cookies VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (identity, user["id"], body.name.strip(), domain, secret, now, now),
        )
    return {"id": identity}


@router.delete("/cookies/{identity}")
def delete_cookie(identity: str, request: Request, user: User):
    state = request.app.state
    get_cookie(state, user["id"], identity)
    if state.db.one(
        "SELECT t.id FROM video_tasks v JOIN offline_tasks t ON t.id=v.task_id "
        "WHERE v.cookie_id=%s AND t.state NOT IN ('complete','cancelled')",
        (identity,),
    ):
        raise HTTPException(409, "Cookie 仍被未结束的视频任务使用")
    state.db.execute("DELETE FROM video_cookies WHERE id=%s", (identity,))
    return {"ok": True}


@router.get("/settings")
def settings(request: Request, user: User):
    state = request.app.state
    return {
        "available": all(state.component_registry[name].executable() for name in ("yt-dlp", "ffmpeg")),
        "max_file_size": state.settings.max_file_size,
    }


@router.get("/files/{identity}")
def file_metadata(identity: str, request: Request, user: User):
    row = request.app.state.db.one(
        "SELECT metadata FROM video_entries WHERE node_id=%s AND owner_id=%s", (identity, user["id"])
    )
    if not row:
        raise HTTPException(404, "视频元数据不存在")
    return json.loads(row["metadata"])


@router.get("")
def listing(request: Request, user: User):
    state = request.app.state
    return [
        translate_fields(public_video(state, row), request, "error")
        for row in state.db.all(
            "SELECT * FROM offline_tasks WHERE owner_id=%s AND kind='video' ORDER BY created_at DESC",
            (user["id"],),
        )
    ]


@router.post("", status_code=201)
async def create(body: Create, request: Request, user: User):
    state = request.app.state
    if not settings(request, user)["available"]:
        raise HTTPException(400, "请先联系管理员在设置中安装 yt-dlp 和 ffmpeg")
    sources = list(dict.fromkeys(source.strip() for source in body.sources))
    try:
        for source in sources:
            await public_url(source)
    except (ValueError, OSError):
        raise HTTPException(400, "请输入可访问的公开视频链接") from None
    if body.cookie_id:
        cookie = get_cookie(state, user["id"], body.cookie_id)
        # A Cookie jar is scoped, and initial URLs must belong to the selected website.
        aliases = {"youtube.com": ("youtu.be",), "bilibili.com": ("b23.tv",)}
        for source in sources:
            host = urlsplit(source).hostname
            if not (
                host == cookie["domain"]
                or host.endswith("." + cookie["domain"])
                or host in aliases.get(cookie["domain"], ())
            ):
                raise HTTPException(422, "所选 Cookie 与视频链接的网站不匹配")
    async with state.mutation_lock:
        check_parent(state.db, user["id"], body.parent_id)
        config_id = body.config_id
        if not config_id:
            config = state.db.one("SELECT id FROM configs WHERE owner_id=%s AND is_default=1", (user["id"],))
            if not config:
                raise HTTPException(400, "请先在设置中添加默认 Telegram 存储配置")
            config_id = config["id"]
        get_config(state, user["id"], config_id)
        result = []
        with state.db.connect() as conn:
            for source in sources:
                identity, now = new_id(), time.time()
                conn.execute(
                    "INSERT INTO offline_tasks(id,owner_id,config_id,parent_id,name,kind,source,"
                    "created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        identity,
                        user["id"],
                        config_id,
                        body.parent_id,
                        urlsplit(source).hostname,
                        "video",
                        state.secrets.cipher.encrypt(source.encode()).decode(),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO video_tasks(task_id,cookie_id) VALUES (%s,%s)", (identity, body.cookie_id)
                )
                result.append(identity)
    return result


@router.post("/{identity}/select")
async def select(identity: str, body: Selection, request: Request, user: User):
    state = request.app.state
    async with state.mutation_lock:
        task = video_task(state, user["id"], identity)
        if task["state"] != "selecting":
            raise HTTPException(409, "当前任务不允许选择视频")
        try:
            select_entries(state, task, body.positions, body.quality, body.audio_only)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    return {"ok": True}


@router.post("/{identity}/{action}")
async def control(
    identity: str, action: Literal["pause", "resume", "retry", "cancel"], request: Request, user: User
):
    video_task(request.app.state, user["id"], identity)
    return await offline_control(identity, action, request, user)


@router.delete("/{identity}")
async def remove(identity: str, request: Request, user: User):
    video_task(request.app.state, user["id"], identity)
    result = await offline_remove(identity, request, user)
    request.app.state.db.execute("DELETE FROM video_entries WHERE task_id IS NULL AND node_id IS NULL")
    return result
