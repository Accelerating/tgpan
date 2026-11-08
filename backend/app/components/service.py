import asyncio
import io
import os
import platform
import shutil
import tarfile
from contextlib import suppress
from pathlib import Path

import httpx

from app.common.processes import command
from app.common.security import new_id


class Components:
    def __init__(self, state):
        self.state = state
        self.root = state.settings.data_dir / "components"
        self.task = None
        self.status = "idle"
        self.error = None
        self.message = ""

    def executable(self):
        managed = self.root / "aria2" / "bin" / "aria2c"
        return str(managed) if managed.is_file() else shutil.which("aria2c")

    async def info(self):
        path = self.executable()
        version = None
        if path:
            try:
                code, output = await command([path, "--version"], timeout=10)
                if code == 0:
                    version = output.splitlines()[0].removeprefix("aria2 version ")
            except (OSError, TimeoutError):
                pass
        return {
            "installed": version is not None,
            "version": version,
            "path": path,
            "managed": bool(path and Path(path).is_relative_to(self.root)),
            "state": self.status,
            "error": self.error,
            "message": self.message,
            "platform": f"{platform.system()} {platform.machine()}",
        }

    def install(self):
        self.status, self.error, self.message = "installing", None, "正在准备安装"
        self.task = asyncio.create_task(self._install())

    async def _install(self):
        candidate = self.root / f"aria2-{new_id()}"
        try:
            target = {
                ("Linux", "x86_64"): "linux-64",
                ("Linux", "aarch64"): "linux-aarch64",
                ("Darwin", "x86_64"): "osx-64",
                ("Darwin", "arm64"): "osx-arm64",
            }.get((platform.system(), platform.machine()))
            if not target:
                raise ValueError("当前系统或 CPU 架构不支持网页安装，请手动安装 aria2")
            bootstrap = self.root / "micromamba"
            if not bootstrap.exists():
                self.message = "正在下载安装工具"
                archive = bytearray()
                async with httpx.AsyncClient(follow_redirects=True, trust_env=False, timeout=60) as client:
                    async with client.stream(
                        "GET", f"https://micro.mamba.pm/api/micromamba/{target}/latest"
                    ) as r:
                        r.raise_for_status()
                        async for chunk in r.aiter_bytes():
                            archive.extend(chunk)
                            if len(archive) > 32 * 1024**2:
                                raise ValueError("组件安装包过大")
                with tarfile.open(fileobj=io.BytesIO(archive), mode="r:bz2") as tar:
                    member = tar.getmember("bin/micromamba")
                    if not member.isfile() or member.size > 64 * 1024**2:
                        raise ValueError("组件安装包无效")
                    temporary = self.root / "micromamba.tmp"
                    with tar.extractfile(member) as source, temporary.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    temporary.chmod(0o700)
                    temporary.replace(bootstrap)
            self.message = "正在安装 aria2 及其运行依赖"
            env = os.environ | {
                "MAMBA_ROOT_PREFIX": str(self.root / "packages"),
                "XDG_CACHE_HOME": str(self.root / "cache"),
                "MAMBA_NO_BANNER": "1",
            }
            code, _ = await command(
                [
                    bootstrap,
                    "--no-rc",
                    "create",
                    "--yes",
                    "--prefix",
                    candidate,
                    "--override-channels",
                    "--channel",
                    "conda-forge",
                    "aria2",
                ],
                env=env,
                timeout=1800,
            )
            if code:
                raise ValueError("aria2 安装失败，请检查网络、磁盘空间或系统兼容性后重试")
            code, _ = await command([candidate / "bin" / "aria2c", "--version"])
            if code:
                raise ValueError("新版本检查失败，已保留原版本")
            # Environments cannot be renamed: their libraries can contain absolute prefixes.
            link = self.root / "aria2.next"
            link.unlink(missing_ok=True)
            link.symlink_to(candidate.name, target_is_directory=True)
            previous = (self.root / "aria2").resolve()
            link.replace(self.root / "aria2")
            if previous != candidate and previous.name.startswith("aria2-"):
                await asyncio.to_thread(shutil.rmtree, previous, True)
            self.status, self.message = "idle", "aria2 已安装并通过检查"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.status = "error"
            self.error = (
                str(error) if isinstance(error, ValueError) else "组件安装失败，请检查网络和磁盘空间后重试"
            )
        finally:
            if (self.root / "aria2").resolve() != candidate:
                await asyncio.to_thread(shutil.rmtree, candidate, True)

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
