from abc import ABC, abstractmethod


class StorageProvider(ABC):
    """Minimal contract for private binary storage implementations."""

    @abstractmethod
    def save(self, content: bytes, suffix: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError
