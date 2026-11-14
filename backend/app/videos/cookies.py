"""User-owned encrypted cookies, converted to domain-scoped Netscape jars."""

import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException


def domain_name(value):
    value = value.strip().lower().lstrip(".")
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", value):
        raise HTTPException(422, "请输入有效的网站域名")
    return value


def normalize_cookie(value, domain):
    value = value.strip()
    lines = [
        line.removeprefix("#HttpOnly_")
        for line in value.splitlines()
        if line and (not line.startswith("#") or line.startswith("#HttpOnly_"))
    ]
    if "\t" in value:
        if not lines:
            raise HTTPException(422, "Cookie 格式无效")
        for line in lines:
            fields = line.split("\t")
            if len(fields) != 7 or fields[0].lstrip(".").lower() != domain:
                raise HTTPException(422, "Cookie 域名必须与配置的网站域名一致")
            if (
                fields[1] not in ("TRUE", "FALSE")
                or fields[3] not in ("TRUE", "FALSE")
                or not fields[2].startswith("/")
                or not fields[4].isdigit()
                or not fields[5]
                or any(ord(char) < 32 for field in fields for char in field)
            ):
                raise HTTPException(422, "Cookie 格式无效")
        return "# Netscape HTTP Cookie File\n" + value + "\n"
    if value.lower().startswith("cookie:"):
        value = value[7:].strip()
    if any(ord(char) < 32 for char in value):
        raise HTTPException(422, "Cookie 格式无效")
    result = ["# Netscape HTTP Cookie File"]
    for pair in value.split(";"):
        name, separator, content = pair.strip().partition("=")
        if not separator or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-zA-Z-]+", name):
            raise HTTPException(422, "Cookie 格式无效")
        result.append(f".{domain}\tTRUE\t/\tTRUE\t0\t{name}\t{content}")
    return "\n".join(result) + "\n"


def get_cookie(state, owner, identity):
    row = state.db.one("SELECT * FROM video_cookies WHERE id=%s AND owner_id=%s", (identity, owner))
    if not row:
        raise HTTPException(404, "Cookie 配置不存在")
    return row


@contextmanager
def cookie_file(state, owner, identity):
    if not identity:
        yield None
        return
    row = get_cookie(state, owner, identity)
    with TemporaryDirectory(prefix="video-cookie-", dir=state.settings.data_dir) as directory:
        path = Path(directory) / "cookies.txt"
        path.touch(mode=0o600)
        path.write_bytes(state.secrets.cipher.decrypt(row["secret"].encode()))
        yield path


def cleanup_cookie_files(state):
    """Remove private jars left behind by an unclean process exit, after taking the app lock."""
    for directory in state.settings.data_dir.glob("video-cookie-*"):
        if directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory)
