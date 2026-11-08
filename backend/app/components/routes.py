from fastapi import APIRouter, HTTPException, Request

from app.common.dependencies import Admin
from app.common.i18n import translate_fields

router = APIRouter(prefix="/api/components/aria2", tags=["components"])


@router.get("")
async def info(request: Request, user: Admin):
    return translate_fields(await request.app.state.components.info(), request, "error", "message")


@router.post("/install", status_code=202)
async def install(request: Request, user: Admin):
    state = request.app.state
    if state.components.status == "installing":
        raise HTTPException(409, "组件正在安装，请稍后")
    if state.offline.running:
        raise HTTPException(409, "请先暂停正在运行的离线任务，再安装或更新组件")
    state.components.install()
    return {"ok": True}
