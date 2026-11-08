"""Read bounded v1 torrent metadata; never trust paths supplied by a torrent."""

from pathlib import PurePosixPath

from fastapi import HTTPException

from app.files.service import clean_name

MAX_TORRENT = 8 * 1024**2


def torrent_files(data):
    if not data or len(data) > MAX_TORRENT:
        raise ValueError("种子无效或超过 8MiB")
    cursor, entries = 0, 0

    def decode(depth=0):
        nonlocal cursor, entries
        entries += 1
        if depth > 100 or entries > 100000 or cursor >= len(data):
            raise ValueError
        token = data[cursor : cursor + 1]
        cursor += 1
        if token == b"i":
            end = data.index(b"e", cursor)
            value = int(data[cursor:end])
            cursor = end + 1
            return value
        if token in (b"l", b"d"):
            result = [] if token == b"l" else {}
            while data[cursor : cursor + 1] != b"e":
                value = decode(depth + 1)
                if token == b"l":
                    result.append(value)
                else:
                    if not isinstance(value, bytes) or value in result:
                        raise ValueError
                    result[value] = decode(depth + 1)
            cursor += 1
            return result
        if not token.isdigit():
            raise ValueError
        end = data.index(b":", cursor - 1)
        size = int(data[cursor - 1 : end])
        cursor = end + 1
        if size < 0 or size > len(data) - cursor:
            raise ValueError
        value = data[cursor : cursor + size]
        cursor += size
        return value

    try:
        metadata = decode()
        if cursor != len(data):
            raise ValueError
        info = metadata[b"info"]
        if b"pieces" not in info or not isinstance(info[b"pieces"], bytes):
            raise ValueError

        def name_part(value):
            text = value.decode("utf-8")
            if clean_name(text) != text:
                raise ValueError
            return text

        name = name_part(info.get(b"name.utf-8", info.get(b"name")))
        raw = info.get(b"files", [{b"length": info.get(b"length"), b"path": []}])
        if not isinstance(raw, list) or not 1 <= len(raw) <= 5000:
            raise ValueError
        files, seen = [], set()
        for index, file in enumerate(raw, 1):
            if b"l" in file.get(b"attr", b"") or b"symlink path" in file:
                raise ValueError
            parts = [name_part(part) for part in file.get(b"path.utf-8", file.get(b"path", []))]
            if len(parts) > 99:
                raise ValueError
            path = str(PurePosixPath(name, *parts))
            size = file[b"length"]
            if type(size) is not int or size < 0 or path in seen or len(path) > 4096:
                raise ValueError
            seen.add(path)
            files.append({"position": index, "path": path, "size": size})
        paths = {file["path"] for file in files}
        if any(str(parent) in paths for path in paths for parent in PurePosixPath(path).parents):
            raise ValueError
        return name, files
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        UnicodeError,
        RecursionError,
        HTTPException,
    ):
        raise ValueError("种子格式无效：仅支持安全路径的 BitTorrent v1 或混合种子") from None
