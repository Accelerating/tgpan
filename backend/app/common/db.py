from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Database:
    def __init__(self, url: str, schema: str = "public"):
        self.pool = ConnectionPool(
            url, min_size=1, max_size=8, open=False, timeout=15,
            kwargs={"row_factory": dict_row, "options": f"-c search_path={schema}", "connect_timeout": 8},
        )

    def open(self):
        self.pool.open(wait=True)

    def close(self):
        self.pool.close()

    @contextmanager
    def connect(self):
        with self.pool.connection() as conn:
            yield conn

    def migrate(self):
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(74647261)")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                conn.execute(Path(__file__).with_name("schema.sql").read_text())
                conn.execute("INSERT INTO schema_version VALUES (1)")
            elif row["version"] != 1:
                raise RuntimeError(f"不支持的数据库版本：{row['version']}")

    def one(self, sql, params=()):
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def all(self, sql, params=()):
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def execute(self, sql, params=()):
        with self.connect() as conn:
            conn.execute(sql, params)
