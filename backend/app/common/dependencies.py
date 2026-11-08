import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request


def current_user(request: Request):
    token = request.cookies.get("tgpan_session", "")
    user = request.app.state.db.one(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token=? AND s.expires>? AND u.disabled=0",
        (request.app.state.secrets_digest(token), time.time()),
    )
    if not user:
        raise HTTPException(401, "请先登录")
    return user


User = Annotated[dict, Depends(current_user)]


def admin_user(user: User):
    if not user["admin"]:
        raise HTTPException(403, "需要管理员权限")
    return user


Admin = Annotated[dict, Depends(admin_user)]
