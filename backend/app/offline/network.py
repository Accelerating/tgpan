import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx


def source_kind(value):
    if any(ord(char) < 32 for char in value) or len(value) > 8192:
        raise ValueError("下载链接无效")
    parsed = urlsplit(value)
    if parsed.scheme == "magnet" and "xt=urn:btih:" in parsed.query:
        return "magnet"
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("仅支持 HTTP、HTTPS 和磁力链接")
    return "http"


async def public_url(value):
    if source_kind(value) != "http":
        raise ValueError("下载链接无效")
    parsed = urlsplit(value)
    await public_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    return value


async def public_addresses(host, port):
    addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("不支持本机、内网或保留地址的下载链接")
    return addresses


async def inspect_http(value):
    """Probe HTTP metadata and validate the initial URL and HEAD redirects."""
    from app.offline.proxy import DownloadProxy

    async with (
        DownloadProxy() as proxy,
        httpx.AsyncClient(
            proxy=proxy.url,
            trust_env=False,
            timeout=10,
        ) as client,
    ):
        for _ in range(6):
            await public_url(value)
            async with client.stream("HEAD", value) as response:
                if response.is_redirect:
                    value = urljoin(value, response.headers.get("location", ""))
                    continue
                # Signed GET URLs may reject HEAD with 403 even though the download is valid.
                if response.status_code not in (403, 405, 501):
                    response.raise_for_status()
                size = response.headers.get("content-length", "")
                return (
                    value,
                    int(size) if size.isdecimal() and response.is_success else None,
                    (
                        response.headers.get("content-type", "").split(";")[0] == "application/x-bittorrent"
                        or urlsplit(value).path.lower().endswith(".torrent")
                    ),
                )
    raise ValueError("下载链接重定向次数过多")
