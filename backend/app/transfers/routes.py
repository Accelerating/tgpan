import hashlib
import os
import re
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.common.dependencies import User, current_user
from app.common.i18n import translate_fields
from app.common.security import new_id
from app.files.delivery import file_response
from app.files.service import add_node
from app.storage.service import get_config
from app.transfers.lifecycle import cancel_upload
from app.transfers.receiving import check_offset, reserve_chunk
from app.transfers.service import block_path, get_upload

router = APIRouter(prefix="/api", tags=["transfers"])


class UploadCreate(BaseModel):
    name: str
    size: int = Field(ge=0)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_id: str | None = None
    config_id: str | None = None
    conflict: Literal["cancel", "keep_both"] = "cancel"


@router.get("/transfers")
def transfers(request: Request, user: User):
    state = request.app.state
    uploads = state.db.all(
        "SELECT u.*,n.name,n.parent_id, "
        "coalesce((SELECT sum(size) FROM blocks WHERE upload_id=u.id AND state='sent'),0) AS stored "
        "FROM uploads u JOIN nodes n ON n.id=u.node_id WHERE u.owner_id=? AND u.origin='browser' "
        "ORDER BY u.created_at DESC",
        (user["id"],),
    )
    for upload in uploads:
        upload["sending_bytes"] = state.worker.progress.get(upload["id"], 0)
    return {
        "uploads": [translate_fields(upload, request, "error") for upload in uploads],
        "cleanup": [
            translate_fields(task, request, "error")
            for task in state.db.all(
                "SELECT id,state,error,created_at FROM cleanup WHERE owner_id=?", (user["id"],)
            )
        ],
    }


@router.post("/uploads", status_code=201)
async def create_upload(body: UploadCreate, request: Request, user: User):
    state = request.app.state
    if body.size > state.settings.max_file_size:
        raise HTTPException(413, "文件超过大小上限")
    async with state.mutation_lock:
        config_id = body.config_id
        if not config_id:
            default = state.db.one("SELECT id FROM configs WHERE owner_id=? AND is_default=1", (user["id"],))
            if not default:
                raise HTTPException(400, "请先在设置中添加默认 Telegram 存储配置")
            config_id = default["id"]
        get_config(state, user["id"], config_id)
        # Reuse an existing task only for an explicit re-selection in the same destination.
        existing = state.db.one(
            "SELECT u.* FROM uploads u JOIN nodes n ON n.id=u.node_id "
            "WHERE u.owner_id=? AND u.fingerprint=? AND u.size=? AND u.config_id=? "
            "AND n.parent_id IS ? AND n.name=? AND n.deleted_at IS NULL "
            "AND u.state IN ('receiving','sending','error')",
            (user["id"], body.fingerprint, body.size, config_id, body.parent_id, body.name),
        )
        if existing:
            return translate_fields(existing, request, "error")
        node = add_node(
            state.db,
            user["id"],
            body.parent_id,
            body.name,
            "file",
            body.size,
            "uploading",
            body.conflict == "keep_both",
        )
        identity, now = new_id(), time.time()
        try:
            state.db.execute(
                "INSERT INTO uploads(id,owner_id,node_id,config_id,fingerprint,size,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (identity, user["id"], node["id"], config_id, body.fingerprint, body.size, now, now),
            )
        except BaseException:
            state.db.execute("DELETE FROM nodes WHERE id=?", (node["id"],))
            raise
        if body.size == 0:
            state.db.execute("UPDATE uploads SET state='complete' WHERE id=?", (identity,))
            state.db.execute("UPDATE nodes SET status='ready' WHERE id=?", (node["id"],))
        return get_upload(state, user["id"], identity)


@router.get("/uploads/{upload_id}")
def upload_status(upload_id: str, request: Request, user: User):
    return translate_fields(get_upload(request.app.state, user["id"], upload_id), request, "error")


@router.put("/uploads/{upload_id}/chunks")
async def chunk(upload_id: str, request: Request, user: User, offset: int = 0):
    state, settings = request.app.state, request.app.state.settings
    checksum = request.headers.get("x-chunk-sha256", "")
    if not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise HTTPException(422, "缺少分块 SHA256 校验值")
    async with reserve_chunk(state, user["id"], upload_id, offset) as (expected, path):
        # Reserve a single HTTP chunk; stream body with an upper bound and timeout.
        hasher, received = hashlib.sha256(), 0
        try:
            import asyncio

            async with asyncio.timeout(120):
                with path.open("wb") as out:
                    async for data in request.stream():
                        received += len(data)
                        if received > expected:
                            raise HTTPException(413, "分块超过预期大小")
                        out.write(data)
                        hasher.update(data)
                    out.flush()
                    os.fsync(out.fileno())
            if received != expected or hasher.hexdigest() != checksum:
                raise HTTPException(422, "分块长度或 SHA256 校验不一致")
            async with state.mutation_lock:
                current_user(request)
                upload = get_upload(state, user["id"], upload_id)
                check_offset(upload, offset)
                position = offset // settings.block_size
                target = block_path(state, upload_id, position)
                committed = offset % settings.block_size
                with target.open("r+b" if target.exists() else "w+b") as out, path.open("rb") as source:
                    out.truncate(committed)
                    out.seek(committed)
                    while data := source.read(64 * 1024):
                        out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                size = committed + received
                block_state = (
                    "queued"
                    if size == settings.block_size or offset + received == upload["size"]
                    else "receiving"
                )
                upload_state = "sending" if offset + received == upload["size"] else "receiving"
                with state.db.connect() as conn:
                    conn.execute(
                        "INSERT INTO blocks(id,upload_id,position,size,state) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(upload_id,position) DO UPDATE SET size=excluded.size,state=excluded.state",
                        (new_id(), upload_id, position, size, block_state),
                    )
                    conn.execute(
                        "UPDATE uploads SET received=?,state=?,updated_at=? WHERE id=?",
                        (offset + received, upload_state, time.time(), upload_id),
                    )
        except TimeoutError:
            raise HTTPException(408, "分块接收超时，请重试该分块") from None
    state.worker.notify()
    return {"received": offset + received}


@router.post("/uploads/{upload_id}/retry")
async def retry(upload_id: str, request: Request, user: User):
    state = request.app.state
    async with state.mutation_lock:
        upload = get_upload(state, user["id"], upload_id)
        if upload["state"] != "error":
            raise HTTPException(409, "当前任务不需要重试")
        blocks = state.db.all("SELECT * FROM blocks WHERE upload_id=? AND state!='sent'", (upload_id,))
        for block in blocks:
            path = block_path(state, upload_id, block["position"])
            if not path.exists() or path.stat().st_size < block["size"]:
                raise HTTPException(409, "临时文件缺失，请取消并重新上传")
        next_state = "sending" if upload["received"] == upload["size"] else "receiving"
        state.db.execute(
            "UPDATE uploads SET state=?,error=NULL,updated_at=? WHERE id=?",
            (next_state, time.time(), upload_id),
        )
    state.worker.notify()
    return {"ok": True}


@router.post("/uploads/{upload_id}/cancel")
async def cancel(upload_id: str, request: Request, user: User):
    state = request.app.state
    async with state.mutation_lock:
        cancel_upload(state, user["id"], upload_id)
    return {"ok": True}


@router.post("/cleanup/retry")
def retry_cleanup(request: Request, user: User):
    request.app.state.db.execute(
        "UPDATE cleanup SET state='queued',error=NULL WHERE owner_id=? AND state='error'", (user["id"],)
    )
    request.app.state.worker.notify()
    return {"ok": True}


@router.get("/files/{node_id}/download")
async def download(node_id: str, request: Request, user: User):
    return await file_response(node_id, request, user)


@router.api_route("/files/{node_id}/preview", methods=["GET", "HEAD"])
async def preview(node_id: str, request: Request, user: User):
    return await file_response(node_id, request, user, inline=True)
