import time

from fastapi import HTTPException

from app.common.security import new_id
from app.transfers.service import block_path, get_upload


def cancel_upload(state, owner, identity):
    """Caller holds mutation_lock; preserve in-flight Telegram cleanup records."""
    upload = get_upload(state, owner, identity)
    if upload["state"] == "complete":
        raise HTTPException(409, "已完成的文件请在文件列表中删除")
    now = time.time()
    with state.db.connect() as conn:
        conn.execute("UPDATE uploads SET state='cancelled',updated_at=? WHERE id=?", (now, identity))
        conn.execute(
            "UPDATE nodes SET status='cancelled',deleted_at=?,trash_root=id WHERE id=?",
            (now, upload["node_id"]),
        )
        for block in conn.execute("SELECT * FROM blocks WHERE upload_id=?", (identity,)).fetchall():
            if block["message_id"]:
                conn.execute(
                    "INSERT OR IGNORE INTO cleanup VALUES (?,?,?,?,?,?,?)",
                    (new_id(), owner, upload["config_id"], block["message_id"], "queued", None, now),
                )
            if block["state"] != "sending":
                block_path(state, identity, block["position"]).unlink(missing_ok=True)
                conn.execute("DELETE FROM blocks WHERE id=?", (block["id"],))
    state.worker.notify()
