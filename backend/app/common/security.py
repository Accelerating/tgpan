import hashlib
import hmac
import os
import secrets
from pathlib import Path

from argon2 import PasswordHasher
from cryptography.fernet import Fernet

passwords = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Secrets:
    def __init__(self, directory: Path):
        path = directory / "secret.key"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as out:
                out.write(Fernet.generate_key())
        self.key = path.read_bytes()
        self.cipher = Fernet(self.key)

    def csrf(self, token: str) -> str:
        return hmac.new(self.key, token.encode(), hashlib.sha256).hexdigest()


def new_id():
    return secrets.token_hex(16)
