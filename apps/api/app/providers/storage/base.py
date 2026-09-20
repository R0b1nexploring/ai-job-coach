from abc import ABC, abstractmethod


class StorageObjectNotFound(Exception):
    """Raised when a provider key no longer exists.

    Business code must treat this as a recoverable cache miss (for example,
    rebuild a missing export) rather than a fatal error.
    """


class StorageProvider(ABC):
    """Minimal contract for private binary storage implementations.

    Keys are opaque provider locators; callers must never build local paths or
    depend on a filesystem layout.
    """

    @abstractmethod
    def save(self, content: bytes, suffix: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def read(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError
