import re
import time
from urllib.parse import quote

from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.files.media import media_type
from app.files.service import get_node
from app.storage.service import get_config, safe_error


def byte_range(header, size):
    if not header:
        return 0, size - 1, 200
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()) or size == 0:
        raise HTTPException(416, "不支持该下载范围", headers={"Content-Range": f"bytes */{size}"})
    start, end = match.groups()
    if not start:
        start, end = max(0, size - int(end)), size - 1
    else:
        start, end = int(start), min(int(end), size - 1) if end else size - 1
    if start > end or start >= size:
        raise HTTPException(416, "下载范围超出文件大小", headers={"Content-Range": f"bytes */{size}"})
    return start, end, 206


async def file_response(node_id: str, request: Request, user: dict, inline=False, authorize=None):
    if authorize:
        authorize()
    state = request.app.state
    node = get_node(state.db, user["id"], node_id)
    if node["kind"] != "file" or node["status"] != "ready":
        raise HTTPException(409, "文件尚不可下载")
    mime = media_type(node["name"]) if inline else "application/octet-stream"
    if inline and not mime:
        raise HTTPException(415, "此格式暂不支持在线预览，请下载后打开")
    upload = state.db.one("SELECT * FROM uploads WHERE node_id=%s AND state='complete'", (node_id,))
    if not upload:
        raise HTTPException(409, "文件存储记录不完整")
    start, end, status = byte_range(request.headers.get("range"), node["size"])
    if inline and status == 206:
        end = min(end, start + 4 * 1024**2 - 1)
    blocks = state.db.all("SELECT * FROM blocks WHERE upload_id=%s ORDER BY position", (upload["id"],))
    if any(not block["file_id"] for block in blocks):
        raise HTTPException(409, "文件存储记录不完整，请重新上传")
    config = get_config(state, user["id"], upload["config_id"])

    headers = {
        "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(node['name'], safe='')}",
        "Content-Length": str(max(0, end - start + 1)),
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{node['size']}"
    if inline:
        headers["Content-Security-Policy"] = "sandbox"
    if request.method == "HEAD":
        return Response(status_code=status, media_type=mime, headers=headers)
    slot = state.preview_slots if inline else state.download_lock

    async def stream():
        # Bound concurrent reads without buffering entire files; preview seeks have two slots.
        import asyncio

        try:
            await asyncio.wait_for(slot.acquire(), timeout=60)
        except TimeoutError:
            raise HTTPException(429, "下载排队超时，请稍后重试", headers={"Retry-After": "3"}) from None
        state.active_downloads[node_id] += 1
        try:
            if authorize:
                authorize()
            get_node(state.db, user["id"], node_id)
            next_check = 0
            cursor = 0
            for block in blocks:
                left, right = max(start, cursor), min(end + 1, cursor + block["size"])
                if left < right:
                    iterator = state.storage.download(config, block["file_id"], left - cursor, right - left)
                    try:
                        async for data in iterator:
                            if authorize and time.monotonic() >= next_check:
                                authorize()
                                next_check = time.monotonic() + 1
                            if await request.is_disconnected():
                                return
                            yield data
                    finally:
                        await iterator.aclose()
                cursor += block["size"]
        finally:
            state.active_downloads[node_id] -= 1
            if not state.active_downloads[node_id]:
                del state.active_downloads[node_id]
            slot.release()

    iterator = stream()
    # Surface initial permission/network failures as JSON rather than a successful empty download.
    try:
        first = await anext(iterator, b"")
    except HTTPException:
        await iterator.aclose()
        raise
    except Exception as error:
        await iterator.aclose()
        detail = "文件暂时无法读取，请稍后重试" if authorize else safe_error(error)
        raise HTTPException(502, detail) from None

    async def body():
        try:
            if first:
                yield first
            async for data in iterator:
                yield data
        finally:
            await iterator.aclose()

    return StreamingResponse(body(), status_code=status, media_type=mime, headers=headers)
