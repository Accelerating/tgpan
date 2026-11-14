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


@pytest.fixture
def migration_db(monkeypatch):
    from app.common import migrations

    baseline = {1: migrations.migration_files()[1]}
    monkeypatch.setattr(migrations, "migration_files", lambda: baseline.copy())
    settings = Settings()
    db = Database(settings.database_url, settings.database_schema)
    db.open()
    try:
        yield db
    finally:
        db.close()


def test_sequential_upgrades_preserve_data_and_run_once(migration_db, tmp_path, monkeypatch):
    from app.common import migrations

    db = migration_db
    db.migrate()
    db.execute("INSERT INTO users VALUES ('one','Admin','hash',1,0,0)")
    files = migrations.migration_files()
    for version, statement in {
        2: "ALTER TABLE users ADD COLUMN note TEXT DEFAULT 'retained';",
        3: "UPDATE users SET note=note || '-updated';",
    }.items():
        path = tmp_path / f"{version}.sql"
        path.write_text(statement)
        files[version] = path
    monkeypatch.setattr(migrations, "migration_files", lambda: files)
    db.migrate()
    db.migrate()
    assert db.one("SELECT version FROM schema_version")["version"] == 3
    assert db.one("SELECT note FROM users WHERE id='one'")["note"] == "retained-updated"


def test_failed_upgrade_rolls_back_all_pending_versions(migration_db, tmp_path, monkeypatch):
    from app.common import migrations

    db = migration_db
    db.migrate()
    files = migrations.migration_files()
    for version, statement in {2: "CREATE TABLE upgrade_probe (id INTEGER);", 3: "SELECT 1/0;"}.items():
        path = tmp_path / f"{version}.sql"
        path.write_text(statement)
        files[version] = path
    monkeypatch.setattr(migrations, "migration_files", lambda: files)
    with pytest.raises(psycopg.errors.DivisionByZero):
        db.migrate()
    assert db.one("SELECT version FROM schema_version")["version"] == 1
    assert db.one("SELECT to_regclass('upgrade_probe') AS name")["name"] is None


def test_new_database_runs_all_versions(migration_db, tmp_path, monkeypatch):
    from app.common import migrations

    files = migrations.migration_files()
    path = tmp_path / "002.sql"
    path.write_text("ALTER TABLE users ADD COLUMN note TEXT;")
    files[2] = path
    monkeypatch.setattr(migrations, "migration_files", lambda: files)
    migration_db.migrate()
    assert migration_db.one("SELECT version FROM schema_version")["version"] == 2
    assert migration_db.all("SELECT note FROM users") == []


@pytest.mark.parametrize("version", [0, -1, 999])
def test_unsupported_version_is_rejected(migration_db, version):
    migration_db.migrate()
    migration_db.execute("UPDATE schema_version SET version=%s", (version,))
    with pytest.raises(RuntimeError, match="不支持"):
        migration_db.migrate()
    assert migration_db.one("SELECT version FROM schema_version")["version"] == version


@pytest.mark.parametrize("names", [["003_gap.sql"], ["002_a.sql", "002_b.sql"], ["wrong.sql"]])
def test_invalid_migration_files_are_rejected(tmp_path, monkeypatch, names):
    from app.common import migrations

    module = tmp_path / "migrations.py"
    directory = tmp_path / "migrations"
    directory.mkdir()
    for name in names:
        (directory / name).write_text("SELECT 1;")
    monkeypatch.setattr(migrations, "__file__", str(module))
    with pytest.raises(RuntimeError):
        migrations.migration_files()


def test_concurrent_startup_applies_upgrade_once(migration_db, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.common import migrations

    db = migration_db
    db.migrate()
    files = migrations.migration_files()
    path = tmp_path / "002.sql"
    path.write_text("CREATE TABLE upgrade_probe (id INTEGER); INSERT INTO upgrade_probe VALUES (1);")
    files[2] = path
    monkeypatch.setattr(migrations, "migration_files", lambda: files)
    barrier = Barrier(2)

    def start():
        barrier.wait(timeout=10)
        db.migrate()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(start) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    assert db.one("SELECT count(*) FROM upgrade_probe")["count"] == 1
    assert db.one("SELECT version FROM schema_version")["version"] == 2


def test_multiple_version_rows_are_rejected(migration_db):
    migration_db.migrate()
    migration_db.execute("INSERT INTO schema_version VALUES (1)")
    with pytest.raises(RuntimeError, match="只有一条"):
        migration_db.migrate()
