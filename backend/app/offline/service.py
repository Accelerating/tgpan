import asyncio
import os
import re
import shutil
import time
from contextlib import suppress
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException

from app.common.processes import command
from app.common.security import new_id
from app.files.service import clean_name
from app.offline.network import inspect_http
from app.offline.proxy import DownloadProxy
from app.offline.torrent import MAX_TORRENT, torrent_files
from app.transfers.local import import_file

ACTIVE = ("queued", "resolving", "downloading", "storing")
SIZE_ERROR = "文件大小超出限制，不支持此下载"
CAPACITY_ERROR = "离线下载空间不足或任务大小超出容量限制"


def get_task(state, owner, identity):
    task = state.db.one("SELECT * FROM offline_tasks WHERE id=? AND owner_id=?", (identity, owner))
    if not task:
        raise HTTPException(404, "离线任务不存在")
    return task


def task_directory(state, identity):
    return state.settings.data_dir / "offline" / identity


def policy(state):
    return state.db.one("SELECT * FROM offline_settings WHERE id=1")


def files_for(state, identity):
    return state.db.all("SELECT * FROM offline_files WHERE task_id=? ORDER BY position", (identity,))


def set_files(context, identity, files, **task_values):
    with context.db.connect() as conn:
        for file in files:
            conn.execute(
                "INSERT INTO offline_files(id,task_id,position,path,size) VALUES (?,?,?,?,?)",
                (new_id(), identity, file["position"], file["path"], file["size"]),
            )
        if task_values:
            conn.execute(
                f"UPDATE offline_tasks SET {','.join(f'{key}=?' for key in task_values)},updated_at=? WHERE id=?",
                (*task_values.values(), time.time(), identity),
            )


def disk_bytes(directory):
    return sum(
        path.stat().st_size for path in directory.rglob("*") if path.is_file() and not path.is_symlink()
    )


def validate_selection(state, task, files):
    if not files:
        raise ValueError("请至少选择一个文件")
    if any(file["size"] > state.settings.max_file_size for file in files):
        raise ValueError(SIZE_ERROR)
    limits = policy(state)
    total = sum(file["size"] for file in files)
    other = sum(
        max(row["total"] if row["state"] in ACTIVE else 0, disk_bytes(task_directory(state, row["id"])))
        for row in state.db.all("SELECT id,total,state FROM offline_tasks WHERE id!=?", (task["id"],))
    )
    existing = disk_bytes(task_directory(state, task["id"]))
    free = shutil.disk_usage(state.settings.data_dir).free
    if total + other > limits["max_bytes"] or max(0, total - existing) + limits["reserve_bytes"] > free:
        raise ValueError(CAPACITY_ERROR)
    return total


def public_task(state, task):
    files = state.db.all(
        "SELECT f.*,u.node_id,u.state AS upload_state,coalesce((SELECT sum(size) FROM blocks "
        "WHERE upload_id=u.id AND state='sent'),0) AS stored FROM offline_files f "
        "LEFT JOIN uploads u ON u.id=f.upload_id WHERE f.task_id=? ORDER BY f.position",
        (task["id"],),
    )
    stored = sum(
        file["size"] if file["complete"] else file["stored"] + state.worker.progress.get(file["upload_id"], 0)
        for file in files
        if file["selected"]
    )
    progress = state.offline.progress.get(task["id"], {})
    return {key: value for key, value in task.items() if key != "source"} | {
        "files": files,
        "stored": min(stored, task["total"]),
        "download_speed": progress.get("speed", 0) if task["state"] == "downloading" else 0,
        "store_speed": state.offline.store_speed(task["id"], stored) if task["state"] == "storing" else 0,
    }


class OfflineWorker:
    def __init__(self, state):
        self.state = state
        self.running = {}
        self.progress = {}
        self.samples = {}
        self.loop_task = None

    def store_speed(self, identity, stored):
        now = time.monotonic()
        samples = self.samples.setdefault(identity, [])
        if not samples or now - samples[-1][0] >= 0.5:
            samples.append((now, stored))
        while len(samples) > 2 and now - samples[0][0] > 8:
            samples.pop(0)
        elapsed = now - samples[0][0]
        return max(0, (stored - samples[0][1]) / elapsed) if elapsed > 0.2 else 0

    async def start(self):
        for task in self.state.db.all("SELECT id,state FROM offline_tasks"):
            root = task_directory(self.state, task["id"])
            if task["state"] in ("complete", "cancelled"):
                await asyncio.to_thread(shutil.rmtree, root, True)
            else:
                for file in files_for(self.state, task["id"]):
                    if file["complete"]:
                        (root / "contents" / file["path"]).unlink(missing_ok=True)
        self.state.db.execute(
            "UPDATE offline_tasks SET state='queued' WHERE state IN ('resolving','downloading','storing')"
        )
        self.loop_task = asyncio.create_task(self.run())

    async def stop_task(self, identity):
        task = self.running.get(identity)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def stop(self):
        if self.loop_task:
            self.loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.loop_task
        await asyncio.gather(*(self.stop_task(identity) for identity in list(self.running)))

    async def run(self):
        while True:
            self.running = {identity: task for identity, task in self.running.items() if not task.done()}
            for identity in list(self.running):
                owner = self.state.db.one(
                    "SELECT u.disabled FROM users u JOIN offline_tasks t ON t.owner_id=u.id WHERE t.id=?",
                    (identity,),
                )
                if not owner or owner["disabled"]:
                    self.state.db.execute("UPDATE offline_tasks SET state='paused' WHERE id=?", (identity,))
                    await self.stop_task(identity)
            if self.state.components.status != "installing":
                candidates = self.state.db.all(
                    "SELECT t.* FROM offline_tasks t JOIN users u ON u.id=t.owner_id "
                    "WHERE t.state IN ('queued','resolving','downloading','storing') AND u.disabled=0 "
                    "ORDER BY t.created_at"
                )
                slots = policy(self.state)["concurrency"]
                downloads = sum(
                    not self.state.db.one(
                        "SELECT download_complete FROM offline_tasks WHERE id=?",
                        (identity,),
                    )["download_complete"]
                    for identity in self.running
                )
                importing = any(
                    self.state.db.one(
                        "SELECT download_complete FROM offline_tasks WHERE id=?",
                        (identity,),
                    )["download_complete"]
                    for identity in self.running
                )
                for candidate in candidates:
                    if candidate["id"] in self.running:
                        continue
                    if candidate["download_complete"]:
                        if importing:
                            continue
                        importing = True
                    else:
                        if downloads >= slots:
                            continue
                        downloads += 1
                    self.running[candidate["id"]] = asyncio.create_task(self.execute(candidate))
            await asyncio.sleep(0.5)

    def update(self, identity, **values):
        values["updated_at"] = time.time()
        self.state.db.execute(
            f"UPDATE offline_tasks SET {','.join(f'{key}=?' for key in values)} WHERE id=?",
            (*values.values(), identity),
        )

    async def execute(self, task):
        identity = task["id"]
        try:
            root = task_directory(self.state, identity)
            root.mkdir(exist_ok=True, mode=0o700)
            (root / "contents").mkdir(exist_ok=True, mode=0o700)
            if task["download_complete"]:
                await self.store(task)
                return
            if task["phase"] == "resolve":
                await self.resolve(task)
                return
            files = [file for file in files_for(self.state, identity) if file["selected"]]
            total = validate_selection(self.state, task, files)
            self.update(identity, state="downloading", phase="download", total=total, error=None)
            source = self.state.secrets.cipher.decrypt(task["source"].encode()).decode()
            args = ["--dir=" + str(root / "contents")]
            if task["kind"] == "http":
                source, size, _ = await inspect_http(source)
                if size is not None and size > self.state.settings.max_file_size:
                    raise ValueError(SIZE_ERROR)
                if size is not None:
                    files[0]["size"] = size
                    total = validate_selection(self.state, task, files)
                    self.state.db.execute(
                        "UPDATE offline_files SET size=? WHERE id=?", (size, files[0]["id"])
                    )
                    self.update(identity, total=total)
                args += ["--out=" + files[0]["path"], source]
            else:
                args += [
                    "--select-file=" + ",".join(str(file["position"]) for file in files),
                    root / "source.torrent",
                ]
            await self.download(task, args)
            actual = []
            for file in files:
                path = root / "contents" / file["path"]
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or not path.resolve().is_relative_to(root / "contents")
                ):
                    raise ValueError("下载文件缺失或大小不一致，请取消后重新创建任务")
                size = path.stat().st_size
                if task["kind"] != "http" and size != file["size"]:
                    raise ValueError("下载文件缺失或大小不一致，请取消后重新创建任务")
                actual.append(file | {"size": size})
            total = validate_selection(self.state, task, actual)
            with self.state.db.connect() as conn:
                for file in actual:
                    conn.execute("UPDATE offline_files SET size=? WHERE id=?", (file["size"], file["id"]))
            self.update(
                identity, state="queued", phase="store", download_complete=1, downloaded=total, total=total
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            detail = (
                str(error)
                if isinstance(error, (ValueError, HTTPException))
                else "离线任务失败，请检查网络和磁盘空间后重试"
            )
            if isinstance(error, HTTPException):
                detail = error.detail
            if detail == SIZE_ERROR:
                await asyncio.to_thread(
                    shutil.rmtree, task_directory(self.state, identity) / "contents", True
                )
            self.update(identity, state="error", error=detail)
        finally:
            self.progress.pop(identity, None)

    async def resolve(self, task):
        state, identity = self.state, task["id"]
        self.update(identity, state="resolving", error=None)
        root = task_directory(state, identity)
        source = state.secrets.cipher.decrypt(task["source"].encode()).decode()
        if task["kind"] == "magnet":
            metadata = root / "metadata"
            metadata.mkdir(exist_ok=True)
            await self.download(
                task, ["--dir=" + str(metadata), "--bt-metadata-only=true", source], metadata=True
            )
            found = list(metadata.glob("*.torrent"))
            if len(found) != 1:
                raise ValueError("无法获取磁力链接的种子信息，请重试或上传种子")
            shutil.copyfile(found[0], root / "source.torrent")
            shutil.rmtree(metadata)
        elif task["kind"] == "http":
            source, size, torrent = await inspect_http(source)
            if torrent:
                if size is not None and size > MAX_TORRENT:
                    raise ValueError("种子无效或超过 8MiB")
                await self.download(
                    task, ["--dir=" + str(root), "--out=source.torrent", source], metadata=True
                )
            else:
                if size is not None and size > state.settings.max_file_size:
                    raise ValueError(SIZE_ERROR)
                try:
                    name = clean_name(unquote(urlsplit(source).path.rsplit("/", 1)[-1]) or "download")
                except HTTPException:
                    name = "download"
                files = [{"position": 1, "path": name, "size": size or 0}]
                total = validate_selection(state, task, files)
                set_files(state, identity, files, name=name, state="queued", phase="download", total=total)
                return
        if (root / "source.torrent").stat().st_size > MAX_TORRENT:
            raise ValueError("种子无效或超过 8MiB")
        name, files = torrent_files((root / "source.torrent").read_bytes())
        set_files(
            state,
            identity,
            files,
            name=name,
            kind="torrent",
            state="selecting",
            phase="download",
            total=sum(file["size"] for file in files),
        )

    async def download(self, task, args, metadata=False):
        state, identity = self.state, task["id"]
        binary = state.components.executable()
        if not binary:
            raise ValueError("请先联系管理员在设置中安装 aria2")
        tail = ""

        async def output(text):
            nonlocal tail
            tail = (tail + text)[-8192:]
            matches = list(re.finditer(r"\s(\d+)B?/(\d+)B?\([^)]*\).*?DL:(\d+)B?", tail))
            if matches and not metadata:
                completed, total, speed = map(int, matches[-1].groups())
                self.progress[identity] = {"speed": speed}
                self.update(identity, downloaded=completed)
                if task["kind"] == "http":
                    if total > state.settings.max_file_size:
                        raise ValueError(SIZE_ERROR)
                    if total:
                        files = files_for(state, identity)
                        files[0]["size"] = total
                        validate_selection(state, task, files)
                        self.update(identity, total=total)

        async def guard():
            while True:
                await asyncio.sleep(0.5)
                limits = policy(state)
                root = task_directory(state, identity)
                used = await asyncio.to_thread(disk_bytes, state.settings.data_dir / "offline")
                if used > limits["max_bytes"] or shutil.disk_usage(root).free < limits["reserve_bytes"]:
                    raise ValueError(CAPACITY_ERROR)
                if metadata:
                    if disk_bytes(root) > MAX_TORRENT * 2:
                        raise ValueError("种子无效或超过 8MiB")
                elif task["kind"] == "http":
                    file = files_for(state, identity)[0]
                    path = root / "contents" / file["path"]
                    if path.exists() and path.stat().st_size > state.settings.max_file_size:
                        raise ValueError(SIZE_ERROR)

        async with DownloadProxy() as proxy:
            env = {
                key: value
                for key, value in os.environ.items()
                if key.lower()
                not in (
                    "http_proxy",
                    "https_proxy",
                    "ftp_proxy",
                    "all_proxy",
                    "no_proxy",
                )
            }
            runner = asyncio.create_task(
                command(
                    [
                        binary,
                        "--no-conf=true",
                        "--no-netrc=true",
                        "--enable-rpc=false",
                        "--all-proxy=" + proxy.url,
                        "--no-proxy=",
                        "--allow-overwrite=false",
                        "--auto-file-renaming=false",
                        "--continue=true",
                        "--file-allocation=none",
                        "--seed-time=0",
                        "--bt-save-metadata=true",
                    "--dht-file-path=" + str(task_directory(state, identity) / "dht.dat"),
                    "--dht-file-path6=" + str(task_directory(state, identity) / "dht6.dat"),
                        "--check-integrity=true",
                        "--follow-torrent=false",
                        "--follow-metalink=false",
                        "--console-log-level=warn",
                        "--enable-color=false",
                        "--human-readable=false",
                        "--summary-interval=1",
                        "--truncate-console-readout=false",
                        "--download-result=hide",
                        "--max-tries=3",
                        "--retry-wait=3",
                        "--stop-with-process=" + str(os.getpid()),
                        *args,
                    ],
                    timeout=180 if metadata else 7 * 86400,
                    output=output,
                    env=env,
                )
            )
            monitor = asyncio.create_task(guard())
            try:
                done, _ = await asyncio.wait([runner, monitor], return_when=asyncio.FIRST_COMPLETED)
                if monitor in done:
                    await monitor
                code, _ = await runner
                if code:
                    raise ValueError(f"下载失败（aria2 退出码 {code}），请检查链接或网络后重试")
            finally:
                for child in (runner, monitor):
                    child.cancel()
                await asyncio.gather(runner, monitor, return_exceptions=True)

    async def store(self, task):
        state, identity = self.state, task["id"]
        self.update(identity, state="storing", phase="store", error=None)
        for file in files_for(state, identity):
            if file["selected"] and not file["complete"]:
                path = task_directory(state, identity) / "contents" / file["path"]
                await import_file(state, task, file, path)
        self.update(identity, state="complete")
        await asyncio.to_thread(shutil.rmtree, task_directory(state, identity), True)
        self.samples.pop(identity, None)
