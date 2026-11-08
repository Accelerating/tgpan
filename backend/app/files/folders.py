import time

from fastapi import HTTPException

from app.common.security import new_id
from app.files.service import check_parent, clean_name


def resolve_folders(db, owner, parent, paths):
    """Resolve relative directory paths atomically, reusing active folders for resume."""
    check_parent(db, owner, parent)
    parts = {path: [clean_name(part) for part in path.split("/")] for path in paths}
    resolved = {(): parent}
    with db.connect() as conn:
        for names in parts.values():
            for depth, name in enumerate(names, 1):
                key = tuple(names[:depth])
                if key in resolved:
                    continue
                if len(resolved) > 5000:
                    raise HTTPException(422, "一次最多上传 5000 个目录")
                destination = resolved[key[:-1]]
                node = conn.execute(
                    "SELECT id,kind FROM nodes WHERE owner_id=? AND parent_id IS ? "
                    "AND name=? AND deleted_at IS NULL",
                    (owner, destination, name),
                ).fetchone()
                if node and node["kind"] != "folder":
                    raise HTTPException(409, f"目标目录中已存在同名项目「{name}」，请更改名称或选择其他目录")
                identity = node["id"] if node else new_id()
                if not node:
                    now = time.time()
                    conn.execute(
                        "INSERT INTO nodes(id,owner_id,parent_id,name,kind,created_at,updated_at) "
                        "VALUES (?,?,?,?,'folder',?,?)",
                        (identity, owner, destination, name, now, now),
                    )
                resolved[key] = identity
    return {path: resolved[tuple(names)] for path, names in parts.items()}
