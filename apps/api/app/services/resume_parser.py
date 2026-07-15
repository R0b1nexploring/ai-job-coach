import io
import re

import pdfplumber
from docx import Document

from app.errors import AppError


ALLOWED = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/pdf": ".pdf",
}


def parse_resume(content: bytes, media_type: str, filename: str) -> tuple[str, list[dict]]:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected = ALLOWED.get(media_type)
    if not expected or suffix != expected:
        raise AppError("UNSUPPORTED_RESUME_TYPE", "仅支持 DOCX 或文本型 PDF 文件。", 415)
    try:
        if suffix == ".docx":
            doc = Document(io.BytesIO(content))
            parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        parts.append(" | ".join(dict.fromkeys(cells)))
            text = "\n".join(parts)
        else:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
            if not text:
                raise AppError(
                    "SCANNED_PDF_UNSUPPORTED", "该 PDF 可能是扫描件，MVP 暂不支持 OCR。", 422
                )
    except AppError:
        raise
    except Exception as exc:
        raise AppError("RESUME_PARSE_FAILED", "文件无法解析，请确认文件未损坏。", 422) from exc
    if not text.strip():
        raise AppError("EMPTY_RESUME", "简历中没有可解析的文本。", 422)
    facts = extract_facts(text)
    return text, facts


def extract_facts(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 2]
    categories = [
        ("education", r"大学|学院|本科|硕士|专业"),
        ("skills", r"CAD|SolidWorks|Python|SOP|Excel"),
        ("projects", r"项目|设计|课题"),
        ("employment", r"实习|工作|公司"),
    ]
    facts = []
    for line in lines[:80]:
        category = next(
            (cat for cat, pattern in categories if re.search(pattern, line, re.I)), "other"
        )
        facts.append(
            {
                "category": category,
                "label": line[:30],
                "value_json": {"text": line},
                "source_text": line,
            }
        )
    return facts[:30]
