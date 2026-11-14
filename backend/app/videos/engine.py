"""yt-dlp CLI boundary: bounded output, private cookie jars and guarded networking."""

import json
import os
from urllib.parse import urlsplit

from app.common.processes import command
from app.offline.network import public_url
from app.offline.proxy import DownloadProxy
from app.videos.cookies import cookie_file


async def run(state, owner, cookie_id, args, *, output=None, timeout=300):
    binary = state.component_registry["yt-dlp"].executable()
    if not binary:
        raise ValueError("请先联系管理员在设置中安装 yt-dlp 和 ffmpeg")
    env = {
        key: value
        for key, value in os.environ.items()
        if key.lower()
        not in (
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "ftp_proxy",
            "no_proxy",
        )
    }
    managed_bin = state.settings.data_dir / "components" / "yt-dlp" / "bin"
    env["PATH"] = str(managed_bin) + os.pathsep + env.get("PATH", "")
    with cookie_file(state, owner, cookie_id) as jar:
        async with DownloadProxy() as proxy:
            code, _ = await command(
                [
                    binary,
                    "--ignore-config",
                    "--no-plugin-dirs",
                    "--no-cache-dir",
                    "--no-colors",
                    "--socket-timeout",
                    "30",
                    "--retries",
                    "3",
                    "--proxy",
                    proxy.url,
                    *(["--cookies", jar] if jar else []),
                    *args,
                ],
                env=env,
                timeout=timeout,
                output=output,
            )
    if code:
        raise ValueError("视频解析或下载失败，请检查链接、Cookie、组件版本和网络后重试")


async def extract(state, owner, cookie_id, source, *, flat=True):
    await public_url(source)
    data = bytearray()

    async def collect(text):
        data.extend(text.encode())
        if len(data) > 16 * 1024**2:
            raise ValueError("视频列表过大，请使用更小的播放列表")

    await run(
        state,
        owner,
        cookie_id,
        [
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--playlist-end",
            "200",
            *(["--flat-playlist"] if flat else ["--no-playlist"]),
            "--",
            source,
        ],
        output=collect,
    )
    try:
        # Ignore diagnostic lines; only a complete JSON object is accepted.
        return json.loads(next(line for line in data.decode().splitlines() if line.startswith("{")))
    except (ValueError, StopIteration):
        raise ValueError("无法解析视频信息，请更新 yt-dlp 后重试") from None


def metadata(info):
    fields = (
        "id",
        "title",
        "uploader",
        "channel",
        "upload_date",
        "duration",
        "description",
        "width",
        "height",
        "fps",
        "vcodec",
        "acodec",
        "ext",
        "format",
        "format_id",
    )
    result = {key: info.get(key) for key in fields}
    result["site"] = info.get("extractor_key") or info.get("extractor")
    # Store subtitle descriptions, never signed media URLs or HTTP headers.
    result["subtitles"] = {
        key: [{"ext": item.get("ext"), "name": item.get("name")} for item in items]
        for key, items in (info.get("subtitles") or {}).items()
    }
    result["thumbnail"] = safe_url(info.get("thumbnail"))
    result["webpage_url"] = safe_url(info.get("webpage_url") or info.get("original_url"))
    result["qualities"] = sorted(
        {
            int(f["height"])
            for f in info.get("formats", [])
            if isinstance(f.get("height"), (int, float)) and f["height"] > 0
        },
        reverse=True,
    )
    return result


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return (
            value if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username else None
        )
    except ValueError:
        return None


def format_selector(quality, audio_only):
    if audio_only:
        return "bestaudio/best"
    limit = "" if quality == "best" else f"[height<={int(quality)}]"
    return f"bestvideo{limit}+bestaudio/best{limit}"


async def probe_media(state, path):
    from pathlib import Path

    binary = state.component_registry["ffmpeg"].executable()
    probe = Path(binary).with_name("ffprobe") if binary else None
    result = {"ext": path.suffix.lstrip(".")}
    if not probe or not probe.is_file():
        return result
    code, output = await command(
        [
            probe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,avg_frame_rate:format=duration",
            "-of",
            "json",
            path,
        ],
        timeout=30,
    )
    if code:
        return result
    try:
        info = json.loads(output)
        result["duration"] = float(info.get("format", {}).get("duration", 0))
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                result.update(
                    vcodec=stream.get("codec_name"), width=stream.get("width"), height=stream.get("height")
                )
                numerator, _, denominator = stream.get("avg_frame_rate", "0/1").partition("/")
                if float(denominator or 1):
                    result["fps"] = float(numerator) / float(denominator or 1)
            elif stream.get("codec_type") == "audio":
                result["acodec"] = stream.get("codec_name")
    except (ValueError, TypeError):
        pass
    return result
