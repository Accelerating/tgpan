from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.common.migrations import migrate


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
            migrate(conn)

    def one(self, sql, params=()):
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def all(self, sql, params=()):
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def execute(self, sql, params=()):
        with self.connect() as conn:
            conn.execute(sql, params)
