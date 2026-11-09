import time
import unicodedata

from fastapi import HTTPException

from app.common.security import new_id


def clean_name(value: str):
    value = unicodedata.normalize("NFC", value.strip())
    if not value or value in (".", "..") or len(value) > 255 or any(ord(c) < 32 or c in "/\\" for c in value):
        raise HTTPException(422, "名称须为 1～255 个字符，不能包含斜杠或控制字符")
    return value


def get_node(db, owner, node_id, active=True):
    node = db.one("SELECT * FROM nodes WHERE id=%s AND owner_id=%s", (node_id, owner))
    if not node or (active and node["deleted_at"] is not None):
        raise HTTPException(404, "文件或目录不存在")
    return node


def check_parent(db, owner, parent):
    if parent:
        node = get_node(db, owner, parent)
        if node["kind"] != "folder":
            raise HTTPException(400, "目标必须是目录")


def descendants(db, node_id):
    return db.all(
        "WITH RECURSIVE tree AS (SELECT * FROM nodes WHERE id=%s UNION ALL "
        "SELECT n.* FROM nodes n JOIN tree t ON n.parent_id=t.id) SELECT * FROM tree",
        (node_id,),
    )


def has_ready_files(db, owner, node_id):
    return bool(
        db.one(
            "WITH RECURSIVE tree AS ("
            "SELECT id,kind,status FROM nodes WHERE id=%s AND owner_id=%s AND deleted_at IS NULL UNION ALL "
            "SELECT n.id,n.kind,n.status FROM nodes n JOIN tree t ON n.parent_id=t.id "
            "WHERE n.owner_id=%s AND n.deleted_at IS NULL) "
            "SELECT 1 FROM tree WHERE kind='file' AND status='ready' LIMIT 1",
            (node_id, owner, owner),
        )
    )


def add_node(db, owner, parent, name, kind, size=0, status="ready", keep_both=False):
    check_parent(db, owner, parent)
    name = clean_name(name)
    if keep_both:
        original, counter = name, 1
        while db.one(
            "SELECT id FROM nodes WHERE owner_id=%s AND parent_id IS NOT DISTINCT FROM %s AND name=%s AND deleted_at IS NULL",
            (owner, parent, name),
        ):
            stem, dot, suffix = original.rpartition(".")
            name = f"{stem} ({counter}).{suffix}" if dot and stem else f"{original} ({counter})"
            name = clean_name(name)
            counter += 1
    now, identity = time.time(), new_id()
    db.execute(
        "INSERT INTO nodes(id,owner_id,parent_id,name,kind,size,status,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (identity, owner, parent, name, kind, size, status, now, now),
    )
    return get_node(db, owner, identity)


def move_nodes(db, owner, nodes, parent):
    check_parent(db, owner, parent)
    for node in nodes:
        if parent in {item["id"] for item in descendants(db, node["id"])}:
            raise HTTPException(400, "不能移动到自身或子目录")
    with db.connect() as conn:
        for node in nodes:
            conflict = conn.execute(
                "SELECT id FROM nodes WHERE owner_id=%s AND parent_id IS NOT DISTINCT FROM %s AND name=%s "
                "AND deleted_at IS NULL AND id!=%s",
                (owner, parent, node["name"], node["id"]),
            ).fetchone()
            if conflict:
                raise HTTPException(
                    409, f"目标目录中已存在同名项目「{node['name']}」，请更改名称或选择其他目录"
                )
        for node in nodes:
            conn.execute(
                "UPDATE nodes SET parent_id=%s,updated_at=%s WHERE id=%s",
                (parent, time.time(), node["id"]),
            )


def purge_node(state, owner, identity):
    db = state.db
    root = get_node(db, owner, identity, active=False)
    if root["deleted_at"] is None:
        raise HTTPException(400, "请先移入回收站")
    nodes = descendants(db, identity)
    ids = [node["id"] for node in nodes]
    if any(state.active_downloads.get(identity) for identity in ids):
        raise HTTPException(409, "文件正在下载或预览，请结束后再永久删除")
    placeholders = ",".join(["%s"] * len(ids))
    uploads = db.all(f"SELECT id FROM uploads WHERE node_id IN ({placeholders})", ids)
    with db.connect() as conn:
        # Message deletion must survive removal of the file's visible metadata.
        rows = conn.execute(
            f"SELECT u.config_id,b.message_id FROM blocks b JOIN uploads u ON u.id=b.upload_id "
            f"WHERE u.node_id IN ({placeholders}) AND b.message_id IS NOT NULL",
            ids,
        ).fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO cleanup VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (new_id(), owner, row["config_id"], row["message_id"], "queued", None, time.time()),
            )
        conn.execute(f"DELETE FROM uploads WHERE node_id IN ({placeholders})", ids)
        for node in reversed(nodes):
            conn.execute("DELETE FROM nodes WHERE id=%s", (node["id"],))
    for upload in uploads:
        for path in (state.settings.data_dir / "uploads").glob(f"{upload['id']}.*"):
            path.unlink(missing_ok=True)
