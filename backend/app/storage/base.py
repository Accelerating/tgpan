from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredFile:
    message_id: int
    file_id: str


class Storage(Protocol):
    async def test(self, config: dict) -> list[dict]: ...
    async def upload(self, config: dict, path, name: str, progress) -> StoredFile: ...
    async def delete(self, config: dict, message_id: int): ...
    def download(self, config: dict, file_id: str, offset: int, length: int): ...
