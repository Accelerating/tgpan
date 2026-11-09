"""One-time, transactional import of a stopped SQLite deployment."""
import sqlite3
from pathlib import Path

from psycopg import sql

TABLES = (
    "users", "sessions", "configs", "nodes", "uploads", "blocks", "cleanup",
    "login_attempts", "shares", "share_sessions", "offline_settings", "offline_tasks", "offline_files",
)


def import_sqlite(db, path):
    path = Path(path).resolve(strict=True)
    counts = {}
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as source, db.connect() as target:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        version = source.execute("PRAGMA user_version").fetchone()[0]
        if version not in (2, 3, 4):
            raise ValueError(f"不支持的 SQLite 版本：{version}")
        available = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        target.execute("SELECT pg_advisory_xact_lock(74647261)")
        for table in TABLES:
            if table != "offline_settings" and target.execute(
                sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))
            ).fetchone():
                raise ValueError("目标数据库必须为空，拒绝覆盖已有数据")
        for table in TABLES:
            if table not in available:
                continue
            rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
            if table == "nodes":
                # Insert ancestors before children regardless of SQLite physical row order.
                pending = {row["id"]: row for row in rows}
                rows, done = [], set()
                while pending:
                    ready = [r for r in pending.values() if r["parent_id"] is None or r["parent_id"] in done]
                    if not ready:
                        raise ValueError("目录存在循环或缺失父目录")
                    for row in ready:
                        rows.append(row)
                        done.add(row["id"])
                        del pending[row["id"]]
            columns = [r[1] for r in source.execute(f'PRAGMA table_info("{table}")')]
            if table == "offline_settings":
                target.execute("DELETE FROM offline_settings")
            query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns),
            )
            with target.cursor() as cursor:
                cursor.executemany(query, [tuple(row) for row in rows])
            actual = target.execute(sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))).fetchone()["count"]
            if actual != len(rows):
                raise ValueError(f"迁移数量不匹配：{table}")
            counts[table] = actual
    return counts
