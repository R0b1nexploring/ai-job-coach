from typing import Protocol


class OCRProviderError(Exception):
    pass


class BaseOCRProvider(Protocol):
    def extract_text(self, content: bytes) -> str: ...
