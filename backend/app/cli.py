import argparse
import getpass
import time

from app.accounts.routes import Credentials
from app.common.config import Settings
from app.common.db import Database
from app.common.security import Secrets, new_id, passwords


def main():
    parser = argparse.ArgumentParser(description="TG Pan 管理命令")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="初始化唯一管理员")
    create.add_argument("--username", default="admin")
    reset = sub.add_parser("reset-password", help="重置帐号密码并撤销会话")
    reset.add_argument("--username", required=True)
    sub.add_parser("migrate-sqlite", help="导入旧 SQLite 数据（目标须为空）").add_argument("path")
    args = parser.parse_args()
    settings = Settings()
    settings.prepare()
    Secrets(settings.data_dir)
    db = Database(settings.database_url, settings.database_schema)
    db.open()
    db.migrate()
    if args.command == "migrate-sqlite":
        from app.common.sqlite_import import import_sqlite

        try:
            counts = import_sqlite(db, args.path)
            print("迁移完成：", counts)
        finally:
            db.close()
        return
    if args.command == "create-admin" and db.one("SELECT id FROM users WHERE admin=1"):
        parser.error("管理员已存在；如需重置密码请使用 reset-password")
    if args.command == "reset-password" and not db.one(
        "SELECT id FROM users WHERE lower(username)=lower(%s)", (args.username,)
    ):
        parser.error("帐号不存在")
    password = getpass.getpass("密码（至少 10 位）：")
    if password != getpass.getpass("再次输入密码："):
        parser.error("两次密码不一致")
    try:
        credentials = Credentials(username=args.username, password=password)
    except ValueError:
        parser.error("用户名仅允许字母、数字、下划线、点和连字符；密码长度须为 10～128 位")
    hashed = passwords.hash(credentials.password)
    with db.connect() as conn:
        if args.command == "create-admin":
            conn.execute(
                "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)",
                (new_id(), credentials.username, hashed, 1, 0, time.time()),
            )
        else:
            user = conn.execute("SELECT id FROM users WHERE lower(username)=lower(%s)", (credentials.username,)).fetchone()
            conn.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, user["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=%s", (user["id"],))
    db.close()
    print("帐号操作完成")


if __name__ == "__main__":
    main()
