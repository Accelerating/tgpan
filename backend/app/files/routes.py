import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.common.dependencies import User
from app.files.folders import resolve_folders
from app.files.media import preview_kind
from app.files.service import (
    add_node,
    check_parent,
    clean_name,
    descendants,
    get_node,
    move_nodes,
    purge_node,
)

router = APIRouter(prefix="/api/files", tags=["files"])


class Folder(BaseModel):
    name: str
    parent_id: str | None = None


class NodeEdit(BaseModel):
    name: str | None = None
    parent_id: str | None = None


class FolderPaths(BaseModel):
    parent_id: str | None = None
    paths: list[str] = Field(min_length=1, max_length=5000)


class Selection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["trash", "restore", "purge", "move"]
    parent_id: str | None = None


@router.get("")
def listing(
    request: Request,
    user: User,
    parent_id: str | None = None,
    q: str = "",
    trash: bool = False,
    sort: Literal["name", "size", "updated_at"] = "name",
    descending: bool = False,
):
    db, owner = request.app.state.db, user["id"]
    check_parent(db, owner, parent_id) if not trash else None
    if trash:
        rows = db.all(
            "SELECT * FROM nodes WHERE owner_id=? AND trash_root=id ORDER BY deleted_at DESC", (owner,)
        )
    else:
        rows = db.all(
            "SELECT * FROM nodes WHERE owner_id=? AND parent_id IS ? AND deleted_at IS NULL",
            (owner, parent_id),
        )
    rows = [r for r in rows if q.casefold() in r["name"].casefold()]
    rows.sort(key=lambda r: r[sort].casefold() if sort == "name" else r[sort], reverse=descending)
    rows.sort(key=lambda r: r["kind"] != "folder")
    crumbs = []
    current = parent_id if not trash else None
    while current:
        node = get_node(db, owner, current)
        crumbs.insert(0, {"id": node["id"], "name": node["name"]})
        current = node["parent_id"]
    for row in rows:
        row["preview_kind"] = (
            preview_kind(row["name"]) if row["kind"] == "file" and row["status"] == "ready" else None
        )
    return {"items": rows, "breadcrumbs": crumbs}


@router.get("/folders")
def folders(request: Request, user: User):
    return request.app.state.db.all(
        "SELECT id,name,parent_id FROM nodes WHERE owner_id=? "
        "AND kind='folder' AND deleted_at IS NULL ORDER BY name",
        (user["id"],),
    )


@router.post("/folders", status_code=201)
async def create_folder(body: Folder, request: Request, user: User):
    return add_node(request.app.state.db, user["id"], body.parent_id, body.name, "folder")


@router.post("/folders/resolve")
async def upload_folders(body: FolderPaths, request: Request, user: User):
    if any(len(path) > 4096 or path.count("/") >= 100 for path in body.paths):
        raise HTTPException(422, "目录路径过长或层级过深")
    async with request.app.state.mutation_lock:
        return resolve_folders(request.app.state.db, user["id"], body.parent_id, body.paths)


@router.patch("/{node_id}")
async def edit_node(node_id: str, body: NodeEdit, request: Request, user: User):
    db = request.app.state.db
    node = get_node(db, user["id"], node_id)
    parent = body.parent_id if "parent_id" in body.model_fields_set else node["parent_id"]
    check_parent(db, user["id"], parent)
    if parent in {n["id"] for n in descendants(db, node_id)}:
        raise HTTPException(400, "不能移动到自身或子目录")
    db.execute(
        "UPDATE nodes SET name=?,parent_id=?,updated_at=? WHERE id=?",
        (clean_name(body.name) if body.name is not None else node["name"], parent, time.time(), node_id),
    )
    return get_node(db, user["id"], node_id)


@router.post("/batch")
async def batch(body: Selection, request: Request, user: User):
    state, owner = request.app.state, user["id"]
    # Serialize filesystem mutations against block upload and remote worker completion.
    async with state.mutation_lock:
        selected = [
            get_node(state.db, owner, identity, active=body.action not in ("restore", "purge"))
            for identity in dict.fromkeys(body.ids)
        ]
        skip = set()
        for root in selected:
            skip.update(n["id"] for n in descendants(state.db, root["id"]) if n["id"] != root["id"])
        if body.action == "move":
            move_nodes(state.db, owner, [node for node in selected if node["id"] not in skip], body.parent_id)
            return {"ok": True}
        for node in selected:
            if node["id"] in skip:
                continue
            tree = descendants(state.db, node["id"])
            if body.action == "purge":
                if any(n["status"] == "uploading" for n in tree):
                    raise HTTPException(409, "请先取消未完成的上传")
                purge_node(state, owner, node["id"])
            elif body.action == "trash":
                if any(n["status"] == "uploading" for n in tree):
                    raise HTTPException(409, "目录中存在未完成的上传，请先取消")
                with state.db.connect() as conn:
                    for n in tree:
                        if n["deleted_at"] is None:
                            conn.execute(
                                "UPDATE nodes SET deleted_at=?,trash_root=? WHERE id=?",
                                (time.time(), node["id"], n["id"]),
                            )
                            conn.execute(
                                "UPDATE shares SET revoked_at=? WHERE node_id=? AND revoked_at IS NULL",
                                (time.time(), n["id"]),
                            )
                            conn.execute(
                                "DELETE FROM share_sessions WHERE share_id IN (SELECT id FROM shares WHERE node_id=?)",
                                (n["id"],),
                            )
            elif body.action == "restore":
                if node["status"] == "cancelled":
                    raise HTTPException(409, "未完成的上传不能恢复，请永久删除后重新上传")
                if node["trash_root"] != node["id"]:
                    raise HTTPException(400, "请恢复回收站中的顶层项目")
                parent = node["parent_id"]
                if parent:
                    original = get_node(state.db, owner, parent, active=False)
                    if original["deleted_at"] is not None:
                        parent = None
                with state.db.connect() as conn:
                    conn.execute("UPDATE nodes SET parent_id=? WHERE id=?", (parent, node["id"]))
                    conn.execute(
                        "UPDATE nodes SET deleted_at=NULL,trash_root=NULL WHERE trash_root=?", (node["id"],)
                    )
    return {"ok": True}
