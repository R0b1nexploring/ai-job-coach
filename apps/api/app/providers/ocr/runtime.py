from .base import OCRProviderError
from .rapidocr import RapidOCRProvider


def extract_jd_text(content: bytes) -> tuple[str, str]:
    """Extract JD text locally and expose the provider name for result transparency."""
    try:
        return RapidOCRProvider().extract_text(content), "rapidocr"
    except OCRProviderError:
        raise
