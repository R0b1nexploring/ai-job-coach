from app.config import get_settings

from .base import StorageProvider
from .local import LocalStorage


def get_storage() -> StorageProvider:
    """Resolve only concrete providers; never silently substitute local storage."""
    provider = get_settings().storage_provider.strip().lower()
    if provider == "local":
        return LocalStorage()
    if provider == "s3":
        from .s3 import S3Storage

        return S3Storage()
    raise RuntimeError(f"未实现的 Storage Provider：{provider or 'empty'}")
