import os
import secrets
from pathlib import Path

from app.config import get_settings

from .base import StorageProvider


class LocalStorage(StorageProvider):
    def __init__(self):
        self.root = get_settings().resolved_storage_path()
        if self.root.is_symlink():
            raise RuntimeError("本地存储根目录不得是符号链接。")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix" and not self.root.is_symlink():
            self.root.chmod(0o700)

    def save(self, content: bytes, suffix: str) -> str:
        key = f"{secrets.token_hex(16)}{suffix.lower()}"
        path = self.root / key
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as file_handle:
                file_handle.write(content)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if os.name == "posix":
            path.chmod(0o600)
        return key

    def path(self, key: str) -> Path:
        safe = Path(key).name
        return self.root / safe

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)
