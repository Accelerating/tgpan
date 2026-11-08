import secrets
import time
from datetime import datetime

from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.common.dependencies import User, current_user
from app.common.i18n import translate
from app.common.limits import client_address
from app.common.security import digest, new_id, passwords
from app.files.delivery import file_response
from app.files.service import get_node, has_ready_files
from app.shares.service import (
    COOKIE,
    authorize_share,
    folder_listing,
    has_access,
    live_share,
    owner_info,
    public_info,
    shared_node,
)

router = APIRouter(prefix="/api", tags=["shares"])


class ShareCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    node_id: str
    password: str | None = Field(default=None, min_length=4, max_length=128)
    expires_at: datetime | None = None


class Unlock(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.get("/shares")
def listing(request: Request, user: User, node_id: str | None = None):
    state = request.app.state
    rows = state.db.all(
        "SELECT s.*,n.name FROM shares s JOIN nodes n ON n.id=s.node_id WHERE s.owner_id=? "
        "AND (? IS NULL OR s.node_id=?) ORDER BY s.created_at DESC",
        (user["id"], node_id, node_id),
    )
    return [owner_info(state, row) for row in rows]


@router.post("/shares", status_code=201)
async def create(body: ShareCreate, request: Request, user: User):
    state = request.app.state
    expiry = None
    if body.expires_at is not None:
        if body.expires_at.tzinfo is None or body.expires_at.timestamp() <= time.time():
            raise HTTPException(422, "有效期须为带时区的未来时间")
        expiry = body.expires_at.timestamp()
    hashed = None
    if body.password:
        with state.password_slots.acquire(f"account:{user['id']}"):
            hashed = await run_in_threadpool(passwords.hash, body.password)
    async with state.mutation_lock:
        current_user(request)
        node = get_node(state.db, user["id"], body.node_id)
        if node["status"] != "ready":
            raise HTTPException(409, "只能分享目录或上传完成的文件")
        if node["kind"] == "folder" and not has_ready_files(state.db, user["id"], node["id"]):
            raise HTTPException(409, "目录中没有已完成的文件，不能分享")
        token = secrets.token_urlsafe(32)
        identity = new_id()
        state.db.execute(
            "INSERT INTO shares VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                identity,
                user["id"],
                node["id"],
                digest(token),
                state.secrets.cipher.encrypt(token.encode()).decode(),
                hashed,
                expiry,
                None,
                time.time(),
                body.title.strip() or translate("好东西", request),
            ),
        )
        row = state.db.one(
            "SELECT s.*,n.name FROM shares s JOIN nodes n ON n.id=s.node_id WHERE s.id=?", (identity,)
        )
        return owner_info(state, row)


@router.delete("/shares/{share_id}")
async def revoke(share_id: str, request: Request, user: User):
    state = request.app.state
    async with state.mutation_lock:
        if not state.db.one("SELECT id FROM shares WHERE id=? AND owner_id=?", (share_id, user["id"])):
            raise HTTPException(404, "分享不存在")
        with state.db.connect() as conn:
            conn.execute(
                "UPDATE shares SET revoked_at=coalesce(revoked_at,?) WHERE id=?", (time.time(), share_id)
            )
            conn.execute("DELETE FROM share_sessions WHERE share_id=?", (share_id,))
    return {"ok": True}


@router.get("/public/shares/{token}")
def metadata(token: str, request: Request):
    state = request.app.state
    share = live_share(state, token)
    return (
        public_info(share)
        if has_access(state, share, request)
        else {"requires_password": True, "title": share["title"]}
    )


@router.post("/public/shares/{token}/unlock")
async def unlock(token: str, body: Unlock, request: Request, response: Response):
    state = request.app.state
    share = live_share(state, token)
    if not share["password"]:
        return public_info(share)
    now = time.time()
    address = f"share:{share['id']}:{client_address(request)}"
    with state.db.connect() as conn:
        conn.execute("DELETE FROM login_attempts WHERE time<?", (now - 900,))
        count = conn.execute("SELECT count(*) FROM login_attempts WHERE address=?", (address,)).fetchone()[0]
        if count >= 10:
            raise HTTPException(429, "密码尝试过多，请 15 分钟后重试")
        conn.execute("INSERT INTO login_attempts VALUES (?,?)", (address, now))
    with state.share_password_slots.acquire(address):
        try:
            await run_in_threadpool(passwords.verify, share["password"], body.password)
        except VerificationError:
            raise HTTPException(403, "分享密码不正确") from None
    # Revocation/expiration can happen while password verification is running.
    share = live_share(state, token)
    session = secrets.token_urlsafe(32)
    expiry = min(time.time() + 86400, share["expires_at"] or float("inf"))
    with state.db.connect() as conn:
        conn.execute("DELETE FROM share_sessions WHERE expires_at<=?", (time.time(),))
        conn.execute("INSERT INTO share_sessions VALUES (?,?,?)", (digest(session), share["id"], expiry))
        conn.execute("DELETE FROM login_attempts WHERE address=?", (address,))
    response.set_cookie(
        COOKIE,
        session,
        httponly=True,
        secure=state.settings.secure_cookie,
        samesite="lax",
        max_age=max(1, int(expiry - time.time())),
        path=f"/api/public/shares/{token}",
    )
    return public_info(share)


@router.get("/public/shares/{token}/files")
def shared_listing(token: str, request: Request, parent_id: str | None = None):
    state = request.app.state
    return folder_listing(state, authorize_share(state, token, request), parent_id)


async def shared_file(token, request, inline=False, node_id=None):
    state = request.app.state

    def check():
        share = authorize_share(state, token, request)
        shared_node(state, share, node_id or share["node_id"])
        return share

    share = check()
    return await file_response(
        node_id or share["node_id"], request, {"id": share["owner_id"]}, inline=inline, authorize=check
    )


@router.get("/public/shares/{token}/download")
@router.head("/public/shares/{token}/download", include_in_schema=False)
async def download(token: str, request: Request):
    return await shared_file(token, request)


@router.get("/public/shares/{token}/preview")
@router.head("/public/shares/{token}/preview", include_in_schema=False)
async def preview(token: str, request: Request):
    return await shared_file(token, request, inline=True)


@router.get("/public/shares/{token}/files/{node_id}/download")
@router.head("/public/shares/{token}/files/{node_id}/download", include_in_schema=False)
async def child_download(token: str, node_id: str, request: Request):
    return await shared_file(token, request, node_id=node_id)


@router.get("/public/shares/{token}/files/{node_id}/preview")
@router.head("/public/shares/{token}/files/{node_id}/preview", include_in_schema=False)
async def child_preview(token: str, node_id: str, request: Request):
    return await shared_file(token, request, inline=True, node_id=node_id)
