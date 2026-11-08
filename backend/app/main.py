import asyncio
import fcntl
import hmac
import sqlite3
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException

from app.accounts.routes import router as accounts
from app.common.config import Settings
from app.common.db import Database
from app.common.i18n import detect_locale, translate
from app.common.limits import CapacityLimiter
from app.common.security import Secrets, digest
from app.files.routes import router as files
from app.shares.routes import router as shares
from app.storage.routes import router as storage_routes
from app.storage.telegram import TelegramStorage
from app.transfers.routes import router as transfers
from app.transfers.service import Worker


def create_app(settings: Settings | None = None, storage=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        settings.prepare()
        lock_file = (settings.data_dir / "server.lock").open("w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise RuntimeError("同一数据目录只允许一个后端进程，请勿开启多个 worker") from None
        state = app.state
        state.settings = settings
        state.db = Database(settings.data_dir / "tgpan.db")
        state.db.migrate()
        state.secrets = Secrets(settings.data_dir)
        state.secrets_digest = digest
        state.storage = storage or TelegramStorage(settings, state.secrets)
        state.mutation_lock = asyncio.Lock()
        state.upload_slots = CapacityLimiter(2)
        state.upload_reservations = {}
        state.storage_test_slots = CapacityLimiter(2)
        state.testing_configs = set()
        state.password_slots = CapacityLimiter(4)
        state.download_lock = asyncio.Lock()
        state.preview_slots = asyncio.Semaphore(2)
        state.share_password_slots = CapacityLimiter(2)
        state.active_downloads = Counter()
        state.worker = Worker(state)
        await state.worker.start()
        try:
            yield
        finally:
            await state.worker.stop()
            lock_file.close()

    app = FastAPI(
        title="Pan",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.enable_api_docs else None,
        openapi_url="/api/openapi.json" if settings.enable_api_docs else None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            allowed = settings.public_origin.rstrip("/") or str(request.base_url).rstrip("/")
            if origin and origin.rstrip("/") != allowed:
                return JSONResponse({"detail": translate("请求来源不受信任", request)}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": translate("拒绝跨站请求", request)}, status_code=403)
            share_unlock = (
                request.method == "POST"
                and request.url.path.startswith("/api/public/shares/")
                and request.url.path.endswith("/unlock")
            )
            if request.url.path != "/api/auth/login" and not share_unlock:
                token = request.cookies.get("tgpan_session", "")
                provided = request.headers.get("x-csrf-token", "")
                if token and not hmac.compare_digest(request.app.state.secrets.csrf(token), provided):
                    return JSONResponse({"detail": translate("会话校验失败，请刷新页面", request)}, status_code=403)
            if request.headers.get("content-length", "0") != "0" and not request.url.path.endswith("/chunks"):
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    return JSONResponse({"detail": translate("业务请求请使用 application/json", request)}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(("/s/", "/api/public/shares/")):
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.middleware("http")
    async def language(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Content-Language"] = detect_locale(request.headers.get("accept-language", ""))
            vary = response.headers.get("Vary", "")
            if "accept-language" not in {item.strip().lower() for item in vary.split(",")}:
                response.headers["Vary"] = f"{vary}, Accept-Language" if vary else "Accept-Language"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        detail = translate(error.detail, request) if isinstance(error.detail, str) else error.detail
        return JSONResponse({"detail": detail}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse(
            {"detail": translate("输入内容不符合要求，请检查后重试", request)}, status_code=422
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, error):
        return JSONResponse({"detail": translate("名称已存在或项目仍被引用，请刷新后重试", request)}, status_code=409)

    @app.exception_handler(sqlite3.OperationalError)
    async def unavailable(request, error):
        return JSONResponse({"detail": translate("数据库暂不可用，请检查磁盘空间后重试", request)}, status_code=503)

    @app.exception_handler(OSError)
    async def disk_error(request, error):
        return JSONResponse({"detail": translate("文件读写失败，请检查磁盘空间和目录权限", request)}, status_code=503)

    for router in (accounts, files, storage_routes, transfers, shares):
        app.include_router(router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/system")
    def system(request: Request):
        from app.common.dependencies import current_user

        current_user(request)
        return {
            "max_file_size": settings.max_file_size,
            "chunk_size": settings.chunk_size,
            "block_size": settings.block_size,
            "storage_backend": "bot_api",
        }

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str, request: Request):
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": translate("接口不存在", request)}, status_code=404)
        root = settings.static_dir.resolve()
        asset = (root / path).resolve()
        if asset.is_relative_to(root) and asset.is_file():
            return FileResponse(asset)
        index = root / "index.html"
        if index.exists() and (not path or "." not in path.rsplit("/", 1)[-1]):
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"detail": translate("前端尚未构建或资源不存在，请参阅 docs/deployment.md", request)}, status_code=404
        )

    return app


app = create_app()
