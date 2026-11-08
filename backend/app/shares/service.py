import time

from fastapi import HTTPException

from app.common.security import digest
from app.files.media import preview_kind
from app.files.service import get_node, has_ready_files

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
        or (share["expires_at"] is not None and share["expires_at"] <= time.time())
    ):
        raise HTTPException(404, "分享不存在或已失效")
    if share["kind"] == "folder" and not has_ready_files(state.db, share["owner_id"], share["node_id"]):
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
        "kind": share["kind"],
        "preview_kind": preview_kind(share["name"]) if share["kind"] == "file" else None,
        "expires_at": share["expires_at"],
    }


def shared_node(state, share, node_id):
    """Authorize membership from the current ancestor chain, including during streaming."""
    node = get_node(state.db, share["owner_id"], node_id)
    cursor = node
    while cursor["id"] != share["node_id"]:
        if share["kind"] != "folder" or not cursor["parent_id"]:
            raise HTTPException(404, "文件或目录不存在")
        cursor = get_node(state.db, share["owner_id"], cursor["parent_id"])
    if node["status"] != "ready" or (
        node["kind"] == "folder" and not has_ready_files(state.db, share["owner_id"], node_id)
    ):
        raise HTTPException(404, "文件或目录不存在")
    return node


def folder_listing(state, share, parent_id):
    parent = shared_node(state, share, parent_id or share["node_id"])
    if parent["kind"] != "folder":
        raise HTTPException(400, "目标必须是目录")
    rows = state.db.all(
        "SELECT id,name,kind,size,updated_at FROM nodes WHERE owner_id=? AND parent_id=? "
        "AND deleted_at IS NULL AND status='ready' ORDER BY kind DESC,name COLLATE NOCASE",
        (share["owner_id"], parent["id"]),
    )
    rows = [
        row
        for row in rows
        if row["kind"] == "file" or has_ready_files(state.db, share["owner_id"], row["id"])
    ]
    for row in rows:
        row["preview_kind"] = preview_kind(row["name"]) if row["kind"] == "file" else None
    crumbs = []
    while True:
        crumbs.insert(0, {"id": parent["id"], "name": parent["name"]})
        if parent["id"] == share["node_id"]:
            break
        parent = get_node(state.db, share["owner_id"], parent["parent_id"])
    return {"items": rows, "breadcrumbs": crumbs}


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
