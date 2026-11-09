import sqlite3

import psycopg
import pytest

from app.common.config import Settings
from app.common.db import Database
from app.common.sqlite_import import import_sqlite


def test_import_preserves_values_and_rejects_overwrite(tmp_path):
    settings = Settings()
    source = tmp_path / "old.db"
    with sqlite3.connect(source) as conn:
        conn.executescript("""
            PRAGMA user_version=2;
            CREATE TABLE users(id TEXT,username TEXT,password TEXT,admin INTEGER,disabled INTEGER,created_at REAL);
            INSERT INTO users VALUES ('one','Admin','hash',1,0,1700000000.123456);
        """)
    db = Database(settings.database_url, settings.database_schema)
    db.open()
    try:
        db.migrate()
        assert import_sqlite(db, source) == {"users": 1}
        assert db.one("SELECT * FROM users")["created_at"] == 1700000000.123456
        with pytest.raises(ValueError, match="必须为空"):
            import_sqlite(db, source)
        with pytest.raises(psycopg.IntegrityError):
            db.execute("INSERT INTO users VALUES ('two','ADMIN','hash',0,0,0)")
        assert db.one("SELECT count(*) FROM users")["count"] == 1
        with pytest.raises(RuntimeError):
            with db.connect() as conn:
                conn.execute("UPDATE users SET disabled=1")
                raise RuntimeError("rollback")
        assert db.one("SELECT disabled FROM users")["disabled"] == 0
    finally:
        db.close()
