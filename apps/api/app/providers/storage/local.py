import secrets
from pathlib import Path

from app.config import get_settings


class LocalStorage:
    def __init__(self):
        self.root = get_settings().resolved_storage_path()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, suffix: str) -> str:
        key = f"{secrets.token_hex(16)}{suffix.lower()}"
        (self.root / key).write_bytes(content)
        return key

    def path(self, key: str) -> Path:
        safe = Path(key).name
        return self.root / safe

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

