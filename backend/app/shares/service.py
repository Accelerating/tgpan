import time

from fastapi import HTTPException

from app.common.security import digest
from app.files.media import preview_kind

COOKIE = "tgpan_share"


def live_share(state, token):
    share = state.db.one(
        "SELECT s.*,n.name,n.size,n.kind,n.status,n.deleted_at,u.disabled "
        "FROM shares s JOIN nodes n ON n.id=s.node_id AND n.owner_id=s.owner_id "
        "JOIN users u ON u.id=s.owner_id WHERE s.token_hash=?",
        (digest(token),),
    )
    if (
        not share
        or share["revoked_at"] is not None
        or share["deleted_at"] is not None
        or share["disabled"]
        or share["status"] != "ready"
        or share["kind"] != "file"
        or (share["expires_at"] is not None and share["expires_at"] <= time.time())
    ):
        raise HTTPException(404, "分享不存在或已失效")
    return share


def has_access(state, share, request):
    if not share["password"]:
        return True
    session = request.cookies.get(COOKIE, "")
    return bool(
        session
        and state.db.one(
            "SELECT token_hash FROM share_sessions WHERE token_hash=? AND share_id=? AND expires_at>?",
            (digest(session), share["id"], time.time()),
        )
    )


def authorize_share(state, token, request):
    share = live_share(state, token)
    if not has_access(state, share, request):
        raise HTTPException(403, "请先输入分享密码")
    return share


def public_info(share):
    return {
        "title": share["title"],
        "requires_password": False,
        "name": share["name"],
        "size": share["size"],
        "preview_kind": preview_kind(share["name"]),
        "expires_at": share["expires_at"],
    }


def owner_info(state, share):
    token = state.secrets.cipher.decrypt(share["token_cipher"].encode()).decode()
    status = "active"
    if share["revoked_at"] is not None:
        status = "revoked"
    elif share["expires_at"] is not None and share["expires_at"] <= time.time():
        status = "expired"
    return {key: share[key] for key in ("id", "node_id", "name", "title", "created_at", "expires_at")} | {
        "path": f"/s/{token}",
        "has_password": bool(share["password"]),
        "status": status,
    }
