import argparse
import getpass
import sqlite3
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
    sub.add_parser("backup", help="在线备份数据库到指定路径").add_argument("path")
    args = parser.parse_args()
    settings = Settings()
    settings.prepare()
    Secrets(settings.data_dir)
    db = Database(settings.data_dir / "tgpan.db")
    db.migrate()
    if args.command == "backup":
        with db.connect() as source, sqlite3.connect(args.path) as target:
            source.backup(target)
        print("数据库备份完成；请同时备份 secret.key 和在途上传数据")
        return
    if args.command == "create-admin" and db.one("SELECT id FROM users WHERE admin=1"):
        parser.error("管理员已存在；如需重置密码请使用 reset-password")
    if args.command == "reset-password" and not db.one(
        "SELECT id FROM users WHERE username=?", (args.username,)
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
                "INSERT INTO users VALUES (?,?,?,?,?,?)",
                (new_id(), credentials.username, hashed, 1, 0, time.time()),
            )
        else:
            user = conn.execute("SELECT id FROM users WHERE username=?", (credentials.username,)).fetchone()
            conn.execute("UPDATE users SET password=? WHERE id=?", (hashed, user["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    print("帐号操作完成")


if __name__ == "__main__":
    main()
