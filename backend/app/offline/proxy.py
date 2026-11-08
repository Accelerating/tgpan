"""Private HTTP proxy: validate every destination, including aria2 redirects.

Connect to the validated numeric address so DNS cannot change between checking
and connecting. HTTPS remains end-to-end TLS via CONNECT.
"""

import asyncio
import base64
import secrets
from contextlib import suppress
from urllib.parse import urlsplit

from app.offline.network import public_addresses


class DownloadProxy:
    async def __aenter__(self):
        self.token = secrets.token_hex(24)
        self.auth = "Basic " + base64.b64encode((self.token + ":").encode()).decode()
        self.connections = set()
        self.server = await asyncio.start_server(self.accept, "127.0.0.1", 0, limit=16384)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://{self.token}:@127.0.0.1:{port}"
        return self

    async def __aexit__(self, *args):
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.connections):
            task.cancel()
        await asyncio.gather(*self.connections, return_exceptions=True)

    async def accept(self, reader, writer):
        current = asyncio.current_task()
        self.connections.add(current)
        remote = None
        try:
            async with asyncio.timeout(15):
                header = (await reader.readuntil(b"\r\n\r\n")).decode("iso-8859-1")
                first, *lines = header.strip().split("\r\n")
                method, target, _ = first.split(" ", 2)
                headers = dict(line.split(":", 1) for line in lines if ":" in line)
                auth = next(
                    (value.strip() for key, value in headers.items() if key.lower() == "proxy-authorization"),
                    "",
                )
                if not secrets.compare_digest(auth, self.auth) or method not in ("GET", "HEAD", "CONNECT"):
                    raise ValueError
                parsed = urlsplit("//" + target if method == "CONNECT" else target)
                if method != "CONNECT" and parsed.scheme != "http":
                    raise ValueError
                addresses = await public_addresses(
                    parsed.hostname, parsed.port or (443 if method == "CONNECT" else 80)
                )
                address = addresses[0]
                upstream, remote = await asyncio.open_connection(
                    address[4][0], address[4][1], family=address[0]
                )
                if method == "CONNECT":
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                else:
                    path = parsed.path or "/"
                    if parsed.query:
                        path += "?" + parsed.query
                    forwarded = [f"{method} {path} HTTP/1.1"] + [
                        f"{key}:{value}"
                        for key, value in headers.items()
                        if key.lower() not in ("proxy-authorization", "proxy-connection", "connection")
                    ]
                    remote.write(
                        ("\r\n".join(forwarded) + "\r\nConnection: close\r\n\r\n").encode("iso-8859-1")
                    )
                    await remote.drain()

            async def relay(source, destination):
                while True:
                    async with asyncio.timeout(120):
                        chunk = await source.read(65536)
                    if not chunk:
                        if destination.can_write_eof():
                            with suppress(OSError):
                                destination.write_eof()
                        return
                    destination.write(chunk)
                    await destination.drain()

            streams = [
                asyncio.create_task(relay(reader, remote)),
                asyncio.create_task(relay(upstream, writer)),
            ]
            try:
                await asyncio.gather(*streams)
            finally:
                for stream in streams:
                    stream.cancel()
                await asyncio.gather(*streams, return_exceptions=True)
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            with suppress(OSError):
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
        finally:
            if remote:
                remote.close()
            writer.close()
            self.connections.discard(current)
