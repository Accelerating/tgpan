"""Bounded command execution without a shell, including child-process cleanup."""

import asyncio
import os
import signal
from contextlib import suppress


async def terminate(process):
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), 8)
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


async def command(args, *, cwd=None, env=None, timeout=60, output=None):
    process = await asyncio.create_subprocess_exec(
        *map(str, args),
        cwd=cwd,
        env=env,
        start_new_session=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    tail = b""
    try:
        async with asyncio.timeout(timeout):
            while chunk := await process.stdout.read(8192):
                tail = (tail + chunk)[-16384:]
                if output:
                    await output(chunk.decode("utf-8", "replace"))
            code = await process.wait()
        return code, tail.decode("utf-8", "replace")
    finally:
        await terminate(process)
