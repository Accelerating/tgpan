from fastapi import HTTPException


def check_credentials_snapshot(conn, user):
    current = conn.execute("SELECT password,disabled FROM users WHERE id=%s FOR UPDATE", (user["id"],)).fetchone()
    if not current or current["disabled"] or current["password"] != user["password"]:
        raise HTTPException(401, "帐号状态已更新，请重新登录")
