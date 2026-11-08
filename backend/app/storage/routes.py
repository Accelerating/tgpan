import asyncio
import re
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.common.dependencies import User
from app.common.i18n import translate, translate_fields
from app.common.security import new_id
from app.storage.service import StorageTestFailure, get_config, redact, safe_error

router = APIRouter(prefix="/api/storage", tags=["storage"])


class ConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    token: str = Field(pattern=r"^\d{5,20}:[A-Za-z0-9_-]{20,100}$")
    channel: str = Field(min_length=1, max_length=100)
    is_default: bool = False


class ConfigEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    is_default: bool | None = None


@router.get("")
def configs(request: Request, user: User):
    return [
        redact(c)
        for c in request.app.state.db.all(
            "SELECT * FROM configs WHERE owner_id=? ORDER BY created_at", (user["id"],)
        )
    ]


@router.post("", status_code=201)
async def create(body: ConfigCreate, request: Request, user: User):
    state = request.app.state
    if not re.fullmatch(r"-100\d+|@[A-Za-z][A-Za-z0-9_]{3,}", body.channel):
        raise HTTPException(422, "频道 ID 应为 -100 开头的数字或 @频道用户名")
    identity = new_id()
    token = state.secrets.cipher.encrypt(body.token.encode()).decode()
    with state.db.connect() as conn:
        first = not conn.execute("SELECT id FROM configs WHERE owner_id=?", (user["id"],)).fetchone()
        default = body.is_default or first
        if default:
            conn.execute("UPDATE configs SET is_default=0 WHERE owner_id=?", (user["id"],))
        conn.execute(
            "INSERT INTO configs VALUES (?,?,?,?,?,?,?)",
            (identity, user["id"], body.name.strip(), token, body.channel, default, time.time()),
        )
    return redact(get_config(state, user["id"], identity))


@router.patch("/{config_id}")
async def update(config_id: str, body: ConfigEdit, request: Request, user: User):
    state = request.app.state
    get_config(state, user["id"], config_id)
    with state.db.connect() as conn:
        if body.is_default:
            conn.execute("UPDATE configs SET is_default=0 WHERE owner_id=?", (user["id"],))
            conn.execute("UPDATE configs SET is_default=1 WHERE id=?", (config_id,))
        if body.name is not None:
            conn.execute("UPDATE configs SET name=? WHERE id=?", (body.name.strip(), config_id))
    return {"ok": True}


@router.delete("/{config_id}")
async def remove(config_id: str, request: Request, user: User):
    state = request.app.state
    async with state.mutation_lock:
        get_config(state, user["id"], config_id)
        if (
            state.worker.active_config == config_id
            or config_id in state.testing_configs
            or state.db.one("SELECT id FROM uploads WHERE config_id=?", (config_id,))
            or state.db.one("SELECT id FROM cleanup WHERE config_id=?", (config_id,))
            or state.db.one("SELECT id FROM offline_tasks WHERE config_id=?", (config_id,))
        ):
            raise HTTPException(409, "配置仍被文件或清理任务引用，不能删除")
        state.db.execute("DELETE FROM configs WHERE id=?", (config_id,))
    return {"ok": True}


@router.post("/{config_id}/test")
async def test(config_id: str, request: Request, user: User):
    state = request.app.state

    def result(ok, steps, error=None):
        value = {
            "ok": ok,
            "steps": [
                translate_fields(step, request, "step", "detail")
                if step["step"] in ("上传", "下载校验", "删除")
                else translate_fields(step, request, "step")
                for step in steps
            ],
        }
        if error is not None:
            value["error"] = translate(error, request)
        return value

    with state.storage_test_slots.acquire(user["id"]):
        async with state.mutation_lock:
            config = get_config(state, user["id"], config_id)
            state.testing_configs.add(config_id)
        try:
            steps = await asyncio.wait_for(state.storage.test(config), timeout=90)
            return result(True, steps)
        except StorageTestFailure as error:
            return result(False, error.steps, error.error)
        except Exception as error:
            return result(False, [], safe_error(error))
        finally:
            state.testing_configs.discard(config_id)
