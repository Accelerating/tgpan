from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from app.common.dependencies import Admin
from app.common.i18n import translate_fields

router = APIRouter(prefix="/api/components/{component}", tags=["components"])


@router.get("")
async def info(component: Literal["aria2", "yt-dlp", "ffmpeg"], request: Request, user: Admin):
    return translate_fields(
        await request.app.state.component_registry[component].info(), request, "error", "message"
    )


@router.post("/install", status_code=202)
async def install(component: Literal["aria2", "yt-dlp", "ffmpeg"], request: Request, user: Admin):
    state = request.app.state
    if any(item.status == "installing" for item in state.component_registry.values()):
        raise HTTPException(409, "组件正在安装，请稍后")
    if state.offline.running:
        raise HTTPException(409, "请先暂停正在运行的离线任务，再安装或更新组件")
    state.component_registry[component].install()
    return {"ok": True}
