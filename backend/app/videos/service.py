"""Video task resolution and download; the shared offline worker owns scheduling."""

import asyncio
import json
import shutil
from contextlib import suppress

from app.common.security import new_id
from app.files.service import clean_name
from app.offline.service import (
    CAPACITY_ERROR,
    SIZE_ERROR,
    disk_bytes,
    files_for,
    policy,
    task_directory,
    validate_selection,
)
from app.videos.engine import extract, format_selector, metadata, probe_media, run, safe_url


async def resolve(worker, task):
    state, identity = worker.state, task["id"]
    worker.update(identity, state="resolving", error=None)
    options = state.db.one("SELECT * FROM video_tasks WHERE task_id=%s", (identity,))
    source = state.secrets.cipher.decrypt(task["source"].encode()).decode()
    info = await extract(state, task["owner_id"], options["cookie_id"], source)
    entries = info.get("entries") if info.get("_type") in ("playlist", "multi_video") else [info]
    entries = list(entries or [])
    if not entries:
        raise ValueError("视频列表为空或暂时无法访问")
    collection = info.get("title") or task["name"]
    prepared = []
    for position, entry in enumerate(entries, 1):
        if not entry:
            continue
        url = safe_url(entry.get("webpage_url") or entry.get("url"))
        if not url:
            url = source if len(entries) == 1 else None
        if not url:
            continue
        detail = metadata(entry) | {"title": entry.get("title") or f"Video {position}", "webpage_url": url}
        prepared.append((position, url, detail))
    if not prepared:
        raise ValueError("无法解析视频信息，请更新 yt-dlp 后重试")
    # All entries and the selectable state commit together, preventing duplicate entries on restart.
    with state.db.connect() as conn:
        for position, url, detail in prepared:
            conn.execute(
                "INSERT INTO video_entries(id,task_id,owner_id,position,source,metadata) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    new_id(),
                    identity,
                    task["owner_id"],
                    position,
                    state.secrets.cipher.encrypt(url.encode()).decode(),
                    json.dumps(detail),
                ),
            )
        conn.execute(
            "UPDATE video_tasks SET collection_title=%s WHERE task_id=%s", (collection[:500], identity)
        )
        conn.execute(
            "UPDATE offline_tasks SET state='selecting',phase='download',name=%s WHERE id=%s",
            (collection[:500], identity),
        )


def filename(title):
    title = "".join("_" if char in "/\\" or ord(char) < 32 else char for char in title).strip(" .")[:150]
    try:
        return clean_name(title or "video")
    except Exception:
        return "video"


async def download(worker, task):
    state, identity = worker.state, task["id"]
    options = state.db.one("SELECT * FROM video_tasks WHERE task_id=%s", (identity,))
    entries = state.db.all("SELECT * FROM video_entries WHERE task_id=%s ORDER BY position", (identity,))
    root = task_directory(state, identity)
    contents = root / "contents"
    contents.mkdir(exist_ok=True)
    files = files_for(state, identity)
    worker.update(identity, state="downloading", error=None)
    for file in files:
        if not file["selected"]:
            continue
        entry = next(entry for entry in entries if entry["file_id"] == file["id"])
        if file["size"] and (contents / file["path"]).is_file():
            continue
        source = state.secrets.cipher.decrypt(entry["source"].encode()).decode()
        info = await extract(state, task["owner_id"], options["cookie_id"], source, flat=False)
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            raise ValueError("暂不支持直播或尚未开始的视频")
        estimate = info.get("filesize") or info.get("filesize_approx") or 0
        if estimate > state.settings.max_file_size:
            raise ValueError(SIZE_ERROR)
        work = root / f"work-{file['position']}"
        work.mkdir(exist_ok=True)
        buffer = ""
        streams = {}
        already = sum(f["size"] for f in files if f["selected"] and f["size"])

        async def output(text):
            nonlocal buffer
            buffer += text
            lines = buffer.split("\n")
            buffer = lines.pop()[-32768:]
            for line in lines:
                if line.startswith("PROGRESS:"):
                    with suppress(ValueError, TypeError):
                        progress = json.loads(line[9:])
                        completed = int(progress.get("downloaded_bytes") or 0)
                        expected = int(
                            progress.get("total_bytes") or progress.get("total_bytes_estimate") or 0
                        )
                        streams[progress.get("filename") or "media"] = (completed, expected)
                        worker.progress[identity] = {"speed": progress.get("speed") or 0}
                        worker.update(
                            identity,
                            downloaded=already + sum(value[0] for value in streams.values()),
                            total=already + sum(value[1] for value in streams.values()),
                        )
                elif line.startswith("PROCESS:"):
                    worker.update(identity, phase="processing")

        ffmpeg = state.component_registry["ffmpeg"].executable()
        if not ffmpeg:
            raise ValueError("请先联系管理员在设置中安装 yt-dlp 和 ffmpeg")
        args = [
            "--no-playlist",
            "--newline",
            "--progress",
            "--progress-delta",
            "1",
            "--progress-template",
            "download:PROGRESS:%(progress)j",
            "--progress-template",
            "postprocess:PROCESS:%(progress.status)s",
            "--ffmpeg-location",
            ffmpeg,
            "--downloader",
            "dash,m3u8:native",
            "--format",
            format_selector(options["quality"], options["audio_only"]),
            "--max-filesize",
            str(state.settings.max_file_size),
            "--output",
            str(work / "media.%(ext)s"),
            "--write-info-json",
            "--no-write-playlist-metafiles",
            *(
                ["--extract-audio", "--audio-format", "m4a"]
                if options["audio_only"]
                else ["--merge-output-format", "mp4/mkv"]
            ),
            "--",
            source,
        ]

        async def guard():
            while True:
                await asyncio.sleep(0.5)
                limits = policy(state)
                if (
                    disk_bytes(state.settings.data_dir / "offline") > limits["max_bytes"]
                    or shutil.disk_usage(root).free < limits["reserve_bytes"]
                ):
                    raise ValueError(CAPACITY_ERROR)
                if any(
                    p.stat().st_size > state.settings.max_file_size for p in work.iterdir() if p.is_file()
                ):
                    raise ValueError(SIZE_ERROR)

        runner = asyncio.create_task(
            run(state, task["owner_id"], options["cookie_id"], args, output=output, timeout=7 * 86400)
        )
        monitor = asyncio.create_task(guard())
        try:
            done, _ = await asyncio.wait([runner, monitor], return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                await monitor
            await runner
        finally:
            runner.cancel()
            monitor.cancel()
            await asyncio.gather(runner, monitor, return_exceptions=True)
        media = [
            p
            for p in work.iterdir()
            if p.is_file()
            and p.suffix
            in (
                ".mp4",
                ".mkv",
                ".webm",
                ".m4a",
                ".mp3",
                ".opus",
                ".ogg",
                ".flac",
                ".wav",
                ".aac",
                ".mov",
            )
        ]
        if len(media) != 1:
            raise ValueError("下载文件缺失或合并失败，请更新组件后重试")
        size = media[0].stat().st_size
        total = validate_selection(
            state,
            task,
            [f | {"size": size if f["id"] == file["id"] else f["size"]} for f in files if f["selected"]],
        )
        base = file["path"]
        if file["size"]:
            base = base.rsplit(".", 1)[0]
        relative = base + media[0].suffix
        target = contents / relative
        target.parent.mkdir(exist_ok=True, parents=True)
        # Re-download after an interrupted move is safe: no upload has started yet.
        media[0].replace(target)
        detail = metadata(info)
        info_path = work / "media.info.json"
        if info_path.exists() and info_path.stat().st_size < 16 * 1024**2:
            detail = metadata(json.loads(info_path.read_text()))
        detail.update(await probe_media(state, target))
        detail["webpage_url"] = source
        detail["size"] = size
        with state.db.connect() as conn:
            conn.execute("UPDATE offline_files SET path=%s,size=%s WHERE id=%s", (relative, size, file["id"]))
            conn.execute(
                "UPDATE video_entries SET metadata=%s WHERE id=%s", (json.dumps(detail), entry["id"])
            )
        file.update(path=relative, size=size)
        shutil.rmtree(work, ignore_errors=True)
        worker.update(identity, total=total, phase="download")
    total = sum(f["size"] for f in files if f["selected"])
    worker.update(identity, state="queued", phase="store", download_complete=1, downloaded=total, total=total)


def select(state, task, positions, quality, audio_only):
    entries = state.db.all("SELECT * FROM video_entries WHERE task_id=%s ORDER BY position", (task["id"],))
    selected = [entry for entry in entries if entry["position"] in positions]
    if len(selected) != len(set(positions)):
        raise ValueError("选择的视频不存在")
    options = state.db.one("SELECT * FROM video_tasks WHERE task_id=%s", (task["id"],))
    folder = filename(options["collection_title"]) + "/" if len(entries) > 1 else ""
    files = [
        {
            "position": entry["position"],
            "size": 0,
            "path": folder
            + (f"{entry['position']:03d} - " if folder else "")
            + filename(json.loads(entry["metadata"])["title"]),
        }
        for entry in selected
    ]
    validate_selection(state, task, files)
    with state.db.connect() as conn:
        for file in files:
            file_id = new_id()
            conn.execute(
                "INSERT INTO offline_files(id,task_id,position,path,size) VALUES (%s,%s,%s,%s,%s)",
                (file_id, task["id"], file["position"], file["path"], file["size"]),
            )
            conn.execute(
                "UPDATE video_entries SET file_id=%s WHERE task_id=%s AND position=%s",
                (file_id, task["id"], file["position"]),
            )
        conn.execute(
            "UPDATE video_tasks SET quality=%s,audio_only=%s WHERE task_id=%s",
            (quality, int(audio_only), task["id"]),
        )
        conn.execute("UPDATE offline_tasks SET state='queued' WHERE id=%s", (task["id"],))
