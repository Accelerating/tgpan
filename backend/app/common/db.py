import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE users (
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL
);
CREATE TABLE sessions (
 token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires REAL NOT NULL
);
CREATE TABLE configs (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 token TEXT NOT NULL, channel TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL
);
CREATE UNIQUE INDEX one_default ON configs(owner_id) WHERE is_default = 1;
CREATE TABLE nodes (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 parent_id TEXT REFERENCES nodes(id), name TEXT NOT NULL, kind TEXT NOT NULL,
 size INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ready',
 trash_root TEXT, deleted_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX sibling_name ON nodes(owner_id, ifnull(parent_id, ''), name)
 WHERE deleted_at IS NULL;
CREATE INDEX node_parent ON nodes(owner_id, parent_id);
CREATE TABLE uploads (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 node_id TEXT NOT NULL UNIQUE REFERENCES nodes(id), config_id TEXT NOT NULL REFERENCES configs(id),
 fingerprint TEXT NOT NULL, size INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'receiving', error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE blocks (
 id TEXT PRIMARY KEY, upload_id TEXT NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, size INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'receiving',
 message_id INTEGER, sha256 TEXT, UNIQUE(upload_id, position)
);
CREATE TABLE cleanup (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 config_id TEXT NOT NULL REFERENCES configs(id), message_id INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued', error TEXT, created_at REAL NOT NULL,
 UNIQUE(config_id, message_id)
);
CREATE TABLE login_attempts (address TEXT NOT NULL, time REAL NOT NULL);
PRAGMA user_version=1;
"""


SHARES_SCHEMA = """
BEGIN;
CREATE TABLE shares (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, token_cipher TEXT NOT NULL,
 password TEXT, expires_at REAL, revoked_at REAL, created_at REAL NOT NULL,
 title TEXT NOT NULL DEFAULT '好东西'
);
CREATE INDEX shares_owner ON shares(owner_id, node_id);
CREATE TABLE share_sessions (
 token_hash TEXT PRIMARY KEY, share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
 expires_at REAL NOT NULL
);
PRAGMA user_version=3;
COMMIT;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self):
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                conn.executescript(SCHEMA)
                version = 1
            if version == 1:
                conn.execute("ALTER TABLE blocks ADD COLUMN file_id TEXT")
                conn.execute("PRAGMA user_version=2")
                version = 2
            if version == 2:
                conn.executescript(SHARES_SCHEMA)
            elif version != 3:
                raise RuntimeError(f"不支持的数据库版本：{version}")
            conn.execute("CREATE INDEX IF NOT EXISTS login_attempt_key_time ON login_attempts(address,time)")
            conn.execute("CREATE INDEX IF NOT EXISTS login_attempt_time ON login_attempts(time)")

    def one(self, sql, params=()):
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql, params=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        with self.connect() as conn:
            conn.execute(sql, params)
