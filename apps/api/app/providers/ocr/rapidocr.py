from functools import lru_cache

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from .base import OCRProviderError


@lru_cache(maxsize=1)
def _engine() -> RapidOCR:
    return RapidOCR()


class RapidOCRProvider:
    """Local OCR provider; image contents never leave the process."""

    def __init__(self, engine=None):
        self.engine = engine

    def extract_text(self, content: bytes) -> str:
        try:
            from io import BytesIO

            with Image.open(BytesIO(content)) as image:
                pixels = np.asarray(image.convert("RGB"))
            result, _elapsed = (self.engine or _engine())(pixels)
        except Exception as exc:
            raise OCRProviderError("本地 OCR 无法识别这张截图。") from exc
        lines = []
        for item in result or []:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            value = str(item[1]).strip()
            confidence = float(item[2])
            if value and confidence >= 0.4:
                lines.append(value)
        return "\n".join(lines)
