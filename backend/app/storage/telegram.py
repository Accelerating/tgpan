import re
import secrets as random
from contextlib import asynccontextmanager

import httpx

from app.storage.base import StoredFile
from app.storage.service import StorageTestFailure, TelegramError


class TelegramStorage:
    """Cloud Bot API storage. Message IDs delete attachments; file IDs retrieve their contents."""

    def __init__(self, settings, secrets, transport=None):
        self.settings, self.secrets, self.transport = settings, secrets, transport

    @asynccontextmanager
    async def client(self, config):
        token = self.secrets.cipher.decrypt(config["token"].encode()).decode()
        async with httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}/",
            proxy=self.settings.proxy_url or None,
            transport=self.transport,
            trust_env=False,
            timeout=httpx.Timeout(120, connect=15),
        ) as client:
            yield client, token

    async def call(self, client, method, **kwargs):
        response = await client.post(method, **kwargs)
        try:
            data = response.json()
        except ValueError:
            raise TelegramError(response.status_code) from None
        if not response.is_success or not data.get("ok"):
            raise TelegramError(
                data.get("error_code", response.status_code),
                data.get("description", ""),
                data.get("parameters", {}).get("retry_after"),
            )
        return data["result"]

    async def send(self, client, config, path, name, progress):
        boundary = random.token_hex(20)
        name = name.replace('"', "").replace("\r", "").replace("\n", "")
        prefix = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{config["channel"]}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\nTG Pan · {name}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()
        size = path.stat().st_size

        async def body():
            yield prefix
            current = 0
            with path.open("rb") as source:
                while data := source.read(64 * 1024):
                    yield data
                    current += len(data)
                    await progress(current, size)
            yield suffix

        result = await self.call(
            client,
            "sendDocument",
            content=body(),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(prefix) + size + len(suffix)),
            },
        )
        return StoredFile(result["message_id"], result["document"]["file_id"])

    async def upload(self, config, path, name, progress):
        async with self.client(config) as (client, _):
            return await self.send(client, config, path, name, progress)

    async def delete_message(self, client, config, message_id):
        try:
            await self.call(
                client, "deleteMessage", json={"chat_id": config["channel"], "message_id": message_id}
            )
        except TelegramError as error:
            if not error.message_missing:
                raise

    async def delete(self, config, message_id):
        async with self.client(config) as (client, _):
            await self.delete_message(client, config, message_id)

    async def read(self, client, token, file_id, offset, length):
        file = await self.call(client, "getFile", json={"file_id": file_id})
        path = file.get("file_path", "")
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or ".." in path.split("/") or path.startswith("/"):
            raise ValueError("Telegram 文件地址无效")
        headers = {"Range": f"bytes={offset}-{offset + length - 1}", "Accept-Encoding": "identity"}
        async with client.stream(
            "GET", f"https://api.telegram.org/file/bot{token}/{path}", headers=headers
        ) as response:
            if response.status_code not in (200, 206):
                raise TelegramError(response.status_code)
            skip = offset if response.status_code == 200 else 0
            if response.status_code == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", response.headers.get("Content-Range", ""))
                if not match or int(match[1]) != offset:
                    raise ValueError("Telegram 文件范围与记录不一致")
            async for data in response.aiter_bytes(64 * 1024):
                discard = min(skip, len(data))
                skip -= discard
                data = data[discard:][:length]
                if data:
                    yield data
                    length -= len(data)
                if length == 0:
                    return
            if length:
                raise ValueError("Telegram 文件长度与记录不一致")

    async def download(self, config, file_id, offset, length):
        async with self.client(config) as (client, token):
            iterator = self.read(client, token, file_id, offset, length)
            try:
                async for data in iterator:
                    yield data
            finally:
                await iterator.aclose()

    async def test(self, config):
        results = []
        try:
            async with self.client(config) as (client, token):
                identity = await self.call(client, "getMe", json={})
                if not identity.get("is_bot"):
                    raise ValueError("机器人身份不正确")
                results.append(
                    {"step": "机器人身份", "ok": True, "detail": f"@{identity.get('username', '')}"}
                )
                channel = await self.call(client, "getChat", json={"chat_id": config["channel"]})
                if channel["type"] != "channel":
                    raise ValueError("目标必须是频道，请使用私有频道作为存储")
                member = await self.call(
                    client, "getChatMember", json={"chat_id": config["channel"], "user_id": identity["id"]}
                )
                if member.get("status") != "administrator" or not all(
                    member.get(p) for p in ("can_post_messages", "can_delete_messages")
                ):
                    raise ValueError("请将机器人设为频道管理员，并开启发布消息和删除消息权限")
                results.append({"step": "频道访问与权限", "ok": True, "detail": channel["title"]})
                import tempfile
                from pathlib import Path

                content = b"tgpan connection test\n"
                with tempfile.TemporaryDirectory(dir=self.settings.data_dir) as directory:
                    path = Path(directory) / "tgpan-test.txt"
                    path.write_bytes(content)

                    async def progress(current, total):
                        pass

                    message = await self.send(client, config, path, path.name, progress)
                try:
                    results.append({"step": "上传", "ok": True, "detail": "测试文件已发送"})
                    data = b"".join(
                        [chunk async for chunk in self.read(client, token, message.file_id, 0, len(content))]
                    )
                    if data != content:
                        raise ValueError("下载内容校验失败")
                    results.append({"step": "下载校验", "ok": True, "detail": "内容一致"})
                finally:
                    await self.delete_message(client, config, message.message_id)
                results.append({"step": "删除", "ok": True, "detail": "测试消息已删除"})
        except Exception as error:
            raise StorageTestFailure(results, error) from None
        return results
