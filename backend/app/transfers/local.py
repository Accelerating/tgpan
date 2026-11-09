"""Import a local file through the same bounded Telegram block queue as browser uploads."""

import asyncio
import time

from app.common.local_files import copy_range
from app.common.security import new_id
from app.files.folders import resolve_folders
from app.files.service import add_node
from app.transfers.service import block_path


def repair_import(state, upload_id, source):
    """Rebuild an uncommitted local block from the retained original on explicit retry."""
    for block in state.db.all("SELECT * FROM blocks WHERE upload_id=%s AND state='queued'", (upload_id,)):
        path = block_path(state, upload_id, block["position"])
        if not path.exists() or path.stat().st_size != block["size"]:
            copy_range(source, path, block["position"] * state.settings.block_size, block["size"])


def begin_import(state, task, file):
    parent = task["parent_id"]
    folder, _, name = file["path"].rpartition("/")
    if folder:
        parent = resolve_folders(state.db, task["owner_id"], parent, [folder])[folder]
    node = add_node(state.db, task["owner_id"], parent, name, "file", file["size"], "uploading", True)
    identity, now = new_id(), time.time()
    try:
        with state.db.connect() as conn:
            conn.execute(
                "INSERT INTO uploads(id,owner_id,node_id,config_id,fingerprint,size,created_at,updated_at,origin) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'offline')",
                (
                    identity,
                    task["owner_id"],
                    node["id"],
                    task["config_id"],
                    file["id"],
                    file["size"],
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE offline_files SET upload_id=%s WHERE id=%s", (identity, file["id"]))
            if not file["size"]:
                conn.execute("UPDATE uploads SET state='complete' WHERE id=%s", (identity,))
                conn.execute("UPDATE nodes SET status='ready' WHERE id=%s", (node["id"],))
    except BaseException:
        state.db.execute("DELETE FROM nodes WHERE id=%s", (node["id"],))
        raise
    return identity


async def import_file(state, task, file, path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != file["size"]:
        raise ValueError("下载文件缺失或大小不一致，请取消后重新创建任务")
    async with state.mutation_lock:
        identity = file["upload_id"] or begin_import(state, task, file)
    while True:
        upload = state.db.one("SELECT * FROM uploads WHERE id=%s", (identity,))
        if not upload or upload["state"] in ("cancelled", "expired"):
            raise ValueError("转存任务已被取消，请取消后重新创建离线任务")
        if upload["state"] == "error":
            raise ValueError(upload["error"])
        if upload["state"] == "complete":
            state.db.execute("UPDATE offline_files SET complete=1 WHERE id=%s", (file["id"],))
            path.unlink(missing_ok=True)
            return
        async with state.mutation_lock:
            outstanding = state.db.one(
                "SELECT id FROM blocks WHERE upload_id=%s AND state!='sent'",
                (identity,),
            )
            if upload["received"] < upload["size"] and not outstanding:
                size = min(state.settings.block_size, upload["size"] - upload["received"])
                used = sum(p.stat().st_size for p in (state.settings.data_dir / "uploads").glob("*.part"))
                if used + sum(state.upload_reservations.values()) + size <= state.settings.temp_limit:
                    position = upload["received"] // state.settings.block_size
                    target = block_path(state, identity, position)
                    copy_range(path, target, upload["received"], size)
                    received = upload["received"] + size
                    with state.db.connect() as conn:
                        conn.execute(
                            "INSERT INTO blocks(id,upload_id,position,size,state) VALUES (%s,%s,%s,%s,'queued')",
                            (new_id(), identity, position, size),
                        )
                        conn.execute(
                            "UPDATE uploads SET received=%s,state=%s,updated_at=%s WHERE id=%s",
                            (
                                received,
                                "sending" if received == upload["size"] else "receiving",
                                time.time(),
                                identity,
                            ),
                        )
                    state.worker.notify()
        await asyncio.sleep(0.25)
