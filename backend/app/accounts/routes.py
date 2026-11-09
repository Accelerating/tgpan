import secrets
import time

from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.accounts.service import check_credentials_snapshot
from app.common.dependencies import Admin, User
from app.common.limits import client_address, take_attempts
from app.common.security import digest, new_id, passwords

router = APIRouter(prefix="/api", tags=["accounts"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    password: str = Field(min_length=10, max_length=128)


class UserUpdate(BaseModel):
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


def public(user):
    return {key: user[key] for key in ("id", "username", "admin", "disabled", "created_at")}


@router.post("/auth/login")
async def login(body: Credentials, request: Request, response: Response):
    db, now = request.app.state.db, time.time()
    address = client_address(request)
    attempt = f"login:{digest(body.username.lower())}:{address}"
    take_attempts(db, [(attempt, 10, 900), (f"login-source:{address}", 60, 60)])
    user = db.one("SELECT * FROM users WHERE lower(username)=lower(%s)", (body.username,))
    valid = False
    if user:
        try:
            with request.app.state.password_slots.acquire(attempt):
                valid = await run_in_threadpool(passwords.verify, user["password"], body.password)
        except VerificationError:
            pass
    if not valid or user["disabled"]:
        raise HTTPException(401, "用户名或密码不正确")
    token = secrets.token_urlsafe(32)
    age = request.app.state.settings.session_days * 86400
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(74647262)")
        check_credentials_snapshot(conn, user)
        conn.execute("DELETE FROM sessions WHERE expires<%s", (now,))
        conn.execute("INSERT INTO sessions VALUES (%s,%s,%s)", (digest(token), user["id"], now + age))
        conn.execute("DELETE FROM login_attempts WHERE address=%s", (attempt,))
    response.set_cookie(
        "tgpan_session",
        token,
        max_age=age,
        httponly=True,
        samesite="strict",
        secure=request.app.state.settings.secure_cookie,
        path="/",
    )
    return {"user": public(user), "csrf": request.app.state.secrets.csrf(token)}


@router.get("/auth/me")
def me(request: Request, user: User):
    return {"user": public(user), "csrf": request.app.state.secrets.csrf(request.cookies["tgpan_session"])}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: User):
    request.app.state.db.execute(
        "DELETE FROM sessions WHERE token=%s", (digest(request.cookies["tgpan_session"]),)
    )
    response.delete_cookie("tgpan_session", path="/")
    return {"ok": True}


@router.post("/auth/password")
async def change_password(body: PasswordChange, request: Request, user: User):
    with request.app.state.password_slots.acquire(f"account:{user['id']}"):
        try:
            await run_in_threadpool(passwords.verify, user["password"], body.current_password)
        except VerificationError:
            raise HTTPException(400, "当前密码不正确") from None
        hashed = await run_in_threadpool(passwords.hash, body.password)
    with request.app.state.db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(74647262)")
        check_credentials_snapshot(conn, user)
        conn.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=%s", (user["id"],))
    return {"ok": True}


@router.get("/users")
def users(request: Request, admin: Admin):
    return [public(u) for u in request.app.state.db.all("SELECT * FROM users ORDER BY created_at")]


@router.post("/users", status_code=201)
async def create_user(body: Credentials, request: Request, admin: Admin):
    with request.app.state.password_slots.acquire(f"account:{admin['id']}"):
        hashed = await run_in_threadpool(passwords.hash, body.password)
    user = dict(
        id=new_id(), username=body.username, password=hashed, admin=0, disabled=0, created_at=time.time()
    )
    with request.app.state.db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(74647262)")
        check_credentials_snapshot(conn, admin)
        conn.execute("INSERT INTO users VALUES (%(id)s,%(username)s,%(password)s,%(admin)s,%(disabled)s,%(created_at)s)", user)
    return public(user)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request, admin: Admin):
    db = request.app.state.db
    target = db.one("SELECT * FROM users WHERE id=%s", (user_id,))
    if not target:
        raise HTTPException(404, "用户不存在")
    if target["admin"] and body.disabled:
        raise HTTPException(400, "不能禁用管理员")
    hashed = None
    if body.password:
        with request.app.state.password_slots.acquire(f"account:{admin['id']}"):
            hashed = await run_in_threadpool(passwords.hash, body.password)
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(74647262)")
        check_credentials_snapshot(conn, admin)
        if body.disabled is not None:
            conn.execute("UPDATE users SET disabled=%s WHERE id=%s", (int(body.disabled), user_id))
        if hashed:
            conn.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, user_id))
        if body.disabled or hashed:
            conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    return {"ok": True}
