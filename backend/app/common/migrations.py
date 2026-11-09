from pathlib import Path


def migration_files():
    root = Path(__file__).parent
    files = {1: root / "schema.sql"}
    for path in sorted((root / "migrations").glob("*.sql")):
        prefix, separator, name = path.stem.partition("_")
        if not separator or not prefix.isdecimal() or not name or int(prefix) in files:
            raise RuntimeError(f"无效或重复的数据库升级脚本：{path.name}")
        files[int(prefix)] = path
    if sorted(files) != list(range(1, max(files) + 1)):
        raise RuntimeError("数据库升级脚本版本必须从 1 开始连续递增")
    return files


def migrate(conn):
    files = migration_files()
    conn.execute("SELECT pg_advisory_xact_lock(74647261)")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    if len(rows) > 1:
        raise RuntimeError("数据库版本表必须只有一条记录")
    version = rows[0]["version"] if rows else 0
    if rows and not 1 <= version <= max(files):
        raise RuntimeError(f"不支持的数据库版本：{version}")
    for target in range(version + 1, max(files) + 1):
        conn.execute(files[target].read_text(encoding="utf-8"))
        if target == 1:
            conn.execute("INSERT INTO schema_version VALUES (%s)", (target,))
        else:
            conn.execute("UPDATE schema_version SET version=%s", (target,))
