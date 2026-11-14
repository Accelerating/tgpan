"""Persistent video metadata links survive removal of finished task records."""

import json

from app.offline.service import public_task


def attach_node(conn, file, node):
    conn.execute("UPDATE video_entries SET node_id=%s WHERE file_id=%s", (node["id"], file["id"]))


def public_video(state, task):
    result = public_task(state, task)
    options = state.db.one("SELECT * FROM video_tasks WHERE task_id=%s", (task["id"],))
    entries = state.db.all(
        "SELECT id,position,metadata,file_id,node_id FROM video_entries WHERE task_id=%s ORDER BY position",
        (task["id"],),
    )
    for entry in entries:
        entry["metadata"] = json.loads(entry["metadata"])
    return result | {"options": options, "entries": entries}
