import base64
import binascii
import shutil
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.common.dependencies import Admin, User
from app.common.i18n import translate_fields
from app.common.security import new_id
from app.files.service import check_parent
from app.offline.network import inspect_http, source_kind
from app.offline.service import (
    SIZE_ERROR,
    files_for,
    get_task,
    policy,
    public_task,
    set_files,
    task_directory,
    validate_selection,
)
from app.offline.torrent import torrent_files
from app.storage.service import get_config
from app.transfers.lifecycle import cancel_upload
from app.transfers.local import repair_import

router = APIRouter(prefix="/api/offline", tags=["offline"])


class Create(BaseModel):
    sources: list[str] = Field(default_factory=list, max_length=20)
    torrent: str | None = Field(default=None, max_length=12 * 1024**2)
    parent_id: str | None = None
    config_id: str | None = None


class Selection(BaseModel):
    positions: list[int] = Field(min_length=1, max_length=5000)


class Policy(BaseModel):
    concurrency: int = Field(ge=1, le=4)
    max_bytes: int = Field(ge=1024**2, le=1024**5)
    reserve_bytes: int = Field(ge=0, le=1024**5)


def value_error(error):
    raise HTTPException(413 if str(error) == SIZE_ERROR else 400, str(error)) from None


@router.get("/settings")
def settings(request: Request, user: User):
    state = request.app.state
    return policy(state) | {
        "max_file_size": state.settings.max_file_size,
        "available": bool(state.components.executable()),
        "free_bytes": shutil.disk_usage(state.settings.data_dir).free,
    }


@router.patch("/settings")
async def update_settings(body: Policy, request: Request, user: Admin):
    request.app.state.db.execute(
        "UPDATE offline_settings SET concurrency=%s,max_bytes=%s,reserve_bytes=%s WHERE id=1",
        (body.concurrency, body.max_bytes, body.reserve_bytes),
    )
    return {"ok": True}


@router.get("")
def listing(request: Request, user: User):
    state = request.app.state
    return [
        translate_fields(public_task(state, task), request, "error")
        for task in state.db.all(
            "SELECT * FROM offline_tasks WHERE owner_id=%s AND kind!='video' ORDER BY created_at DESC",
            (user["id"],),
        )
    ]


@router.post("", status_code=201)
async def create(body: Create, request: Request, user: User):
    state = request.app.state
    if not state.components.executable():
        raise HTTPException(400, "请先联系管理员在设置中安装 aria2")
    if bool(body.sources) == bool(body.torrent):
        raise HTTPException(422, "请输入下载链接或上传一个种子文件")
    prepared = []
    try:
        if body.torrent:
            data = base64.b64decode(body.torrent, validate=True)
            name, files = torrent_files(data)
            prepared.append(("torrent", name, "", data, files))
        else:
            for source in dict.fromkeys(body.sources):
                source = source.strip()
                kind = source_kind(source)
                if kind == "http":
                    _, size, is_torrent = await inspect_http(source)
                    if not is_torrent and size is not None and size > state.settings.max_file_size:
                        raise ValueError(SIZE_ERROR)
                prepared.append((kind, urlsplit(source).hostname or "magnet", source, None, []))
    except (ValueError, binascii.Error) as error:
        value_error(error)
    except OSError:
        raise HTTPException(400, "下载链接无法访问，请检查链接和网络") from None
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(400, "下载链接无法访问，请检查链接和网络") from None
    result = []
    async with state.mutation_lock:
        check_parent(state.db, user["id"], body.parent_id)
        config_id = body.config_id
        if not config_id:
            default = state.db.one("SELECT id FROM configs WHERE owner_id=%s AND is_default=1", (user["id"],))
            if not default:
                raise HTTPException(400, "请先在设置中添加默认 Telegram 存储配置")
            config_id = default["id"]
        get_config(state, user["id"], config_id)
        for kind, name, source, data, files in prepared:
            identity, now = new_id(), time.time()
            root = task_directory(state, identity)
            root.mkdir(mode=0o700)
            if data:
                (root / "source.torrent").write_bytes(data)
            state.db.execute(
                "INSERT INTO offline_tasks(id,owner_id,config_id,parent_id,name,kind,source,state,phase,"
                "total,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    identity,
                    user["id"],
                    config_id,
                    body.parent_id,
                    name,
                    kind,
                    state.secrets.cipher.encrypt(source.encode()).decode(),
                    "selecting" if data else "queued",
                    "download" if data else "resolve",
                    sum(file["size"] for file in files),
                    now,
                    now,
                ),
            )
            if files:
                set_files(state, identity, files)
            result.append(public_task(state, get_task(state, user["id"], identity)))
    return result


@router.post("/{identity}/select")
async def select(identity: str, body: Selection, request: Request, user: User):
    state = request.app.state
    async with state.mutation_lock:
        task = get_task(state, user["id"], identity)
        if task["state"] != "selecting":
            raise HTTPException(409, "当前任务不允许选择文件")
        files = files_for(state, identity)
        selected = [file for file in files if file["position"] in body.positions]
        if len(selected) != len(set(body.positions)):
            raise HTTPException(422, "选择的文件不存在")
        try:
            total = validate_selection(state, task, selected)
        except ValueError as error:
            value_error(error)
        with state.db.connect() as conn:
            for file in files:
                conn.execute(
                    "UPDATE offline_files SET selected=%s WHERE id=%s",
                    (
                        int(file["position"] in body.positions),
                        file["id"],
                    ),
                )
            conn.execute(
                "UPDATE offline_tasks SET state='queued',total=%s,updated_at=%s WHERE id=%s",
                (total, time.time(), identity),
            )
    return {"ok": True}


@router.post("/{identity}/{action}")
async def control(
    identity: str, action: Literal["pause", "resume", "retry", "cancel"], request: Request, user: User
):
    state = request.app.state
    async with state.mutation_lock:
        task = get_task(state, user["id"], identity)
        if task["state"] in ("complete", "cancelled"):
            raise HTTPException(409, "任务已结束")
        if action == "pause":
            if task["state"] not in ("queued", "resolving", "downloading", "storing"):
                raise HTTPException(409, "当前任务不能暂停")
            state.offline.update(identity, state="paused")
        elif action in ("resume", "retry"):
            if task["state"] not in ("paused", "error"):
                raise HTTPException(409, "当前任务不需要继续或重试")
            for file in files_for(state, identity):
                if file["upload_id"] and not file["complete"]:
                    try:
                        repair_import(
                            state,
                            file["upload_id"],
                            task_directory(state, identity) / "contents" / file["path"],
                        )
                    except ValueError as error:
                        value_error(error)
                    state.db.execute(
                        "UPDATE uploads SET state=CASE WHEN received=size THEN 'sending' ELSE 'receiving' END,"
                        "error=NULL,updated_at=%s WHERE id=%s AND state='error'",
                        (time.time(), file["upload_id"]),
                    )
            state.offline.update(identity, state="queued", error=None)
            state.worker.notify()
            return {"ok": True}
        else:
            state.offline.update(identity, state="cancelled", error=None)
    await state.offline.stop_task(identity)
    if action == "cancel":
        async with state.mutation_lock:
            for file in files_for(state, identity):
                upload = state.db.one("SELECT state FROM uploads WHERE id=%s", (file["upload_id"],))
                if upload and upload["state"] not in ("complete", "cancelled", "expired"):
                    cancel_upload(state, user["id"], file["upload_id"])
                elif upload and upload["state"] == "complete":
                    state.db.execute("UPDATE offline_files SET complete=1 WHERE id=%s", (file["id"],))
        shutil.rmtree(task_directory(state, identity), ignore_errors=True)
    return {"ok": True}


@router.delete("/{identity}")
async def remove(identity: str, request: Request, user: User):
    state = request.app.state
    async with state.mutation_lock:
        task = get_task(state, user["id"], identity)
        if task["state"] not in ("complete", "cancelled"):
            raise HTTPException(409, "请先取消任务再删除记录")
        if identity in state.offline.running and not state.offline.running[identity].done():
            raise HTTPException(409, "任务正在停止，请稍后")
        state.db.execute("DELETE FROM offline_tasks WHERE id=%s", (identity,))
        state.offline.samples.pop(identity, None)
    return {"ok": True}
