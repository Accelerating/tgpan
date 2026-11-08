from contextlib import asynccontextmanager

from fastapi import HTTPException

from app.transfers.service import get_upload


@asynccontextmanager
async def reserve_chunk(state, owner, upload_id, offset):
    with state.upload_slots.acquire(owner):
        async with state.mutation_lock:
            upload = get_upload(state, owner, upload_id)
            check_offset(upload, offset)
            expected = min(state.settings.chunk_size, upload["size"] - offset)
            directory = state.settings.data_dir / "uploads"
            used = sum(path.stat().st_size for path in directory.glob("*.part"))
            reserved = sum(state.upload_reservations.values())
            if used + reserved + 2 * expected > state.settings.temp_limit:
                raise HTTPException(429, "临时空间已满，请稍后重试", headers={"Retry-After": "3"})
            state.upload_reservations[upload_id] = 2 * expected
        path = directory / f"{upload_id}.incoming"
        try:
            yield expected, path
        finally:
            try:
                path.unlink(missing_ok=True)
            finally:
                state.upload_reservations.pop(upload_id, None)


def check_offset(upload, offset):
    if upload["state"] not in ("receiving", "sending"):
        raise HTTPException(409, "任务已暂停、取消或完成，请刷新任务状态")
    if offset != upload["received"] or offset >= upload["size"]:
        raise HTTPException(409, "上传偏移不一致，请查询任务状态后续传")
