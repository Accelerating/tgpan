import asyncio
import hashlib
import time
from contextlib import suppress

from fastapi import HTTPException

from app.common.security import new_id
from app.files.service import purge_node
from app.storage.service import safe_error


def get_upload(state, owner, identity):
    upload = state.db.one("SELECT * FROM uploads WHERE id=%s AND owner_id=%s", (identity, owner))
    if not upload:
        raise HTTPException(404, "上传任务不存在")
    return upload


def block_path(state, upload_id, position):
    return state.settings.data_dir / "uploads" / f"{upload_id}.{position}.part"


def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class Worker:
    def __init__(self, state):
        self.state = state
        self.wake = asyncio.Event()
        self.active_config = None
        self.progress = {}
        self.task = None

    def recover(self):
        state = self.state
        state.db.execute("UPDATE blocks SET state='queued' WHERE state='sending'")
        state.db.execute("UPDATE cleanup SET state='queued' WHERE state='running'")
        state.db.execute("UPDATE uploads SET state='receiving' WHERE state='sending'")
        for block in state.db.all(
            "SELECT b.*,u.received,u.size AS total FROM blocks b JOIN uploads u ON u.id=b.upload_id"
        ):
            path = block_path(state, block["upload_id"], block["position"])
            if block["state"] == "sent":
                path.unlink(missing_ok=True)
            elif path.exists():
                # A crash after fsync but before the database commit may leave an unacknowledged tail.
                if path.stat().st_size >= block["size"]:
                    with path.open("r+b") as out:
                        out.truncate(block["size"])
                else:
                    state.db.execute(
                        "UPDATE uploads SET state='error',error=%s WHERE id=%s",
                        ("临时文件不完整，请取消后重新上传", block["upload_id"]),
                    )
            elif block["size"]:
                state.db.execute(
                    "UPDATE uploads SET state='error',error=%s WHERE id=%s",
                    ("临时文件丢失，请取消后重新上传", block["upload_id"]),
                )
        known = {
            f"{b['upload_id']}.{b['position']}.part"
            for b in state.db.all("SELECT * FROM blocks WHERE state!='sent'")
        }
        for path in (state.settings.data_dir / "uploads").iterdir():
            if path.name not in known:
                path.unlink(missing_ok=True)
        # A crash can occur after the last message mapping commits, before completion commits.
        with state.db.connect() as conn:
            conn.execute(
                "UPDATE uploads SET state='complete',error=NULL,updated_at=%s "
                "WHERE state IN ('receiving','sending') AND received=size "
                "AND NOT EXISTS (SELECT 1 FROM blocks WHERE upload_id=uploads.id AND state!='sent')",
                (time.time(),),
            )
            conn.execute(
                "UPDATE nodes SET status='ready',updated_at=%s WHERE status='uploading' "
                "AND id IN (SELECT node_id FROM uploads WHERE state='complete')",
                (time.time(),),
            )

    async def start(self):
        self.recover()
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    def notify(self):
        self.wake.set()

    async def run(self):
        while True:
            self.wake.clear()
            try:
                worked = await self.tick()
                if worked:
                    continue
                await self.expire()
            except asyncio.CancelledError:
                raise
            except Exception:
                # State-specific failures are handled in tick; keep housekeeping alive.
                import logging

                logging.getLogger("tgpan.worker").error("后台任务异常，请检查数据库和磁盘")
            with suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=3)

    async def tick(self):
        state, db = self.state, self.state.db
        async with state.mutation_lock:
            block = db.one(
                "SELECT b.*,u.config_id,u.owner_id,u.node_id FROM blocks b JOIN uploads u ON u.id=b.upload_id "
                "JOIN users a ON a.id=u.owner_id WHERE b.state='queued' "
                "AND u.state NOT IN ('error','cancelled','expired') AND a.disabled=0 "
                "AND NOT EXISTS (SELECT 1 FROM offline_files f JOIN offline_tasks t ON t.id=f.task_id "
                "WHERE f.upload_id=u.id AND t.state IN ('paused','error','cancelled')) "
                "ORDER BY u.created_at,b.position LIMIT 1"
            )
            if block:
                db.execute("UPDATE blocks SET state='sending' WHERE id=%s", (block["id"],))
                self.active_config = block["config_id"]
        if block:
            path = block_path(state, block["upload_id"], block["position"])
            config = db.one("SELECT * FROM configs WHERE id=%s", (block["config_id"],))
            try:
                checksum = await asyncio.to_thread(file_hash, path)

                async def progress(current, total):
                    self.progress[block["upload_id"]] = current

                message = await state.storage.upload(
                    config, path, f"{block['upload_id']}.{block['position']}.bin", progress
                )
                async with state.mutation_lock:
                    current = db.one("SELECT * FROM uploads WHERE id=%s", (block["upload_id"],))
                    if not current or current["state"] in ("cancelled", "expired"):
                        db.execute(
                            "INSERT INTO cleanup VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (
                                new_id(),
                                block["owner_id"],
                                config["id"],
                                message.message_id,
                                "queued",
                                None,
                                time.time(),
                            ),
                        )
                        if current:
                            db.execute("DELETE FROM blocks WHERE id=%s", (block["id"],))
                    else:
                        db.execute(
                            "UPDATE blocks SET state='sent',message_id=%s,file_id=%s,sha256=%s WHERE id=%s",
                            (message.message_id, message.file_id, checksum, block["id"]),
                        )
                        remaining = db.one(
                            "SELECT count(*) AS n FROM blocks WHERE upload_id=%s AND state!='sent'",
                            (block["upload_id"],),
                        )["n"]
                        if current["received"] == current["size"] and remaining == 0:
                            with db.connect() as conn:
                                conn.execute(
                                    "UPDATE uploads SET state='complete',error=NULL,updated_at=%s WHERE id=%s",
                                    (time.time(), current["id"]),
                                )
                                conn.execute(
                                    "UPDATE nodes SET status='ready',updated_at=%s WHERE id=%s",
                                    (time.time(), current["node_id"]),
                                )
                path.unlink(missing_ok=True)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                async with state.mutation_lock:
                    current = db.one("SELECT * FROM uploads WHERE id=%s", (block["upload_id"],))
                    if current and current["state"] not in ("cancelled", "expired"):
                        db.execute("UPDATE blocks SET state='queued' WHERE id=%s", (block["id"],))
                        db.execute(
                            "UPDATE uploads SET state='error',error=%s,updated_at=%s WHERE id=%s",
                            (safe_error(error), time.time(), block["upload_id"]),
                        )
                    else:
                        db.execute("DELETE FROM blocks WHERE id=%s", (block["id"],))
                        path.unlink(missing_ok=True)
            finally:
                self.progress.pop(block["upload_id"], None)
                self.active_config = None
            return True
        cleanup = db.one("SELECT * FROM cleanup WHERE state='queued' ORDER BY created_at LIMIT 1")
        if cleanup:
            self.active_config = cleanup["config_id"]
            db.execute("UPDATE cleanup SET state='running' WHERE id=%s", (cleanup["id"],))
            try:
                config = db.one("SELECT * FROM configs WHERE id=%s", (cleanup["config_id"],))
                await state.storage.delete(config, cleanup["message_id"])
                db.execute("DELETE FROM cleanup WHERE id=%s", (cleanup["id"],))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                db.execute(
                    "UPDATE cleanup SET state='error',error=%s WHERE id=%s", (safe_error(error), cleanup["id"])
                )
            finally:
                self.active_config = None
            return True
        return False

    async def expire(self):
        state, now = self.state, time.time()
        async with state.mutation_lock:
            rows = state.db.all(
                "SELECT * FROM uploads WHERE state IN ('receiving','error') AND updated_at<%s "
                "AND origin='browser'",
                (now - state.settings.upload_ttl,),
            )
            for row in rows:
                if row["id"] in state.upload_reservations:
                    continue
                if state.db.one("SELECT id FROM blocks WHERE upload_id=%s AND state='sending'", (row["id"],)):
                    continue
                state.db.execute("UPDATE uploads SET state='expired' WHERE id=%s", (row["id"],))
                state.db.execute(
                    "UPDATE nodes SET status='cancelled',deleted_at=%s,trash_root=id WHERE id=%s",
                    (now, row["node_id"]),
                )
                purge_node(state, row["owner_id"], row["node_id"])
