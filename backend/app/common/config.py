from ipaddress import ip_network
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TGPAN_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    static_dir: Path = Path(__file__).resolve().parents[2] / "static"
    proxy_url: str = ""
    secure_cookie: bool = False
    public_origin: str = ""
    trusted_proxies: str = ""
    enable_api_docs: bool = False
    max_file_size: int = Field(default=5_000_000_000, ge=1)
    block_size: int = Field(default=16 * 1024**2, ge=4096, le=16 * 1024**2)
    chunk_size: int = Field(default=4 * 1024**2, ge=4096, le=16 * 1024**2)
    temp_limit: int = Field(default=2 * 1024**3, ge=4096)
    upload_ttl: int = Field(default=86400, ge=60)
    session_days: int = Field(default=7, ge=1)

    @field_validator("trusted_proxies")
    @classmethod
    def validate_proxies(cls, value):
        for network in value.split(","):
            if network.strip():
                ip_network(network.strip(), strict=False)
        return value

    def prepare(self):
        self.data_dir = self.data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("uploads", "offline", "components"):
            (self.data_dir / name).mkdir(exist_ok=True, mode=0o700)
        if self.chunk_size > self.block_size or self.block_size % self.chunk_size:
            raise ValueError("block_size 必须为 chunk_size 的整数倍")
        if self.temp_limit < self.block_size + self.chunk_size:
            raise ValueError("临时空间至少需要容纳一个存储块和一个上传分块")
