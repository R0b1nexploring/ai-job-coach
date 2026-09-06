"""PDF export with Chromium first, LibreOffice fallback, and physical QA."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.errors import AppError
from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html

A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89


async def export_pdf(content: dict, title: str, snapshot: dict | None = None) -> bytes:
    html = render_resume_html(content, title, snapshot=snapshot)
    pdf = await _chromium_pdf(html)
    if pdf is None:
        pdf = await asyncio.to_thread(_libreoffice_pdf, content, title, snapshot)
    if pdf is None:
        raise AppError(
            "PDF_CONVERTER_UNAVAILABLE",
            "当前环境没有可用的 Chromium 或 LibreOffice，无法导出 PDF。HTML 和 DOCX 仍可下载。",
            503,
        )
    qa = inspect_pdf_bytes(pdf, content)
    if qa["status"] != "passed":
        raise AppError(
            "PDF_QA_FAILED",
            "PDF 未通过单页、裁切、字体或文本层检查，已返回生成修复。",
            422,
            details={"issues": qa["issues"]},
        )
    return pdf


def converter_available() -> bool:
    return _playwright_importable() or bool(shutil.which("soffice") or shutil.which("libreoffice"))


def inspect_pdf_bytes(pdf: bytes, content: dict) -> dict:
    issues: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "resume.pdf"
        path.write_bytes(pdf)
        page_count, width, height = _pdf_geometry(path)
        if page_count != 1:
            issues.append(f"page_count: expected 1, got {page_count}")
        if page_count and (abs(width - A4_WIDTH_PT) > 8 or abs(height - A4_HEIGHT_PT) > 8):
            issues.append("page_size: expected A4 portrait")
        issues.extend(_crop_issues(path, width, height))
        extracted = _pdf_text(path)
        normalized = _normalized(extracted)
        for section in content.get("sections") or []:
            name = str(section.get("name") or "")
            if name and _normalized(name) not in normalized:
                issues.append(f"section:{name}: not visible in PDF text layer")
            for item in section.get("items") or []:
                for bullet in item.get("bullets") or []:
                    text = str(bullet.get("text") or "")
                    if text and _normalized(text) not in normalized:
                        issues.append("bullet: not visible in PDF text layer")
        font_rows = _font_rows(path)
        if not font_rows:
            issues.append("fonts: no fonts detected")
        elif any(row.get("embedded") != "yes" for row in font_rows):
            issues.append("fonts: every font must be embedded")
        elif any(row.get("unicode") != "yes" for row in font_rows):
            issues.append("fonts: every font must include a Unicode map")
    return {"status": "passed" if not issues else "failed", "issues": issues}


def _playwright_importable() -> bool:
    try:
        from playwright.async_api import async_playwright  # noqa: F401

        return True
    except Exception:
        return False


async def _chromium_pdf(html: str) -> bytes | None:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html, wait_until="load")
                return await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                )
            finally:
                await browser.close()
    except Exception:
        return None


def _libreoffice_pdf(content: dict, title: str, snapshot: dict | None = None) -> bytes | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "resume.docx"
        source.write_bytes(render_resume_docx(content, title, snapshot=snapshot))
        completed = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", folder, str(source)],
            capture_output=True,
            check=False,
        )
        output = Path(folder) / "resume.pdf"
        if completed.returncode != 0 or not output.exists():
            return None
        return output.read_bytes()


def _pdf_geometry(path: Path) -> tuple[int, float, float]:
    info = _pdfinfo(path)
    if info:
        return info
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return 0, 0, 0
            page = pdf.pages[0]
            return len(pdf.pages), float(page.width), float(page.height)
    except Exception:
        return 0, 0, 0


def _pdfinfo(path: Path) -> tuple[int, float, float] | None:
    if not shutil.which("pdfinfo"):
        return None
    result = subprocess.run(
        ["pdfinfo", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    pages = re.search(r"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    size = re.search(
        r"^Page size:\s+([\d.]+) x ([\d.]+) pts",
        result.stdout,
        re.MULTILINE,
    )
    if not pages or not size:
        return None
    return int(pages.group(1)), float(size.group(1)), float(size.group(2))


def _pdf_text(path: Path) -> str:
    if shutil.which("pdftotext"):
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""


def _crop_issues(path: Path, width: float, height: float) -> list[str]:
    issues: list[str] = []
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return issues
            page = pdf.pages[0]
            crop = getattr(page, "cropbox", None) or getattr(page, "bbox", None)
            media = getattr(page, "mediabox", None) or (0, 0, width, height)
            if crop and media:
                crop_box = tuple(float(value) for value in crop)
                media_box = tuple(float(value) for value in media)
                if (
                    crop_box[0] - media_box[0] > 2
                    or crop_box[1] - media_box[1] > 2
                    or media_box[2] - crop_box[2] > 2
                    or media_box[3] - crop_box[3] > 2
                ):
                    issues.append("crop: CropBox clips MediaBox")
            for char in page.chars or []:
                x0 = float(char.get("x0") or 0)
                x1 = float(char.get("x1") or 0)
                y0 = float(char.get("top") or char.get("y0") or 0)
                y1 = float(char.get("bottom") or char.get("y1") or 0)
                if x0 < -2 or y0 < -2 or x1 > width + 2 or y1 > height + 2:
                    issues.append("crop: text extends outside A4 page")
                    break
    except Exception:
        return issues
    return issues


def _font_rows(path: Path) -> list[dict[str, str]]:
    if shutil.which("pdffonts"):
        result = subprocess.run(
            ["pdffonts", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        rows = []
        pattern = re.compile(r"\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$")
        for line in result.stdout.splitlines()[2:]:
            match = pattern.search(line)
            if match:
                rows.append(
                    {
                        "embedded": match.group(1),
                        "subset": match.group(2),
                        "unicode": match.group(3),
                    }
                )
        if rows:
            return rows
    return _font_rows_from_pdf_objects(path)


def _font_rows_from_pdf_objects(path: Path) -> list[dict[str, str]]:
    try:
        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdfpage import PDFPage
        from pdfminer.pdfparser import PDFParser
        from pdfminer.pdftypes import resolve1
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    try:
        with path.open("rb") as handle:
            document = PDFDocument(PDFParser(handle))
            seen: set[str] = set()
            for page in PDFPage.create_pages(document):
                resources = resolve1(page.resources) or {}
                fonts = resolve1(resources.get("Font")) or {}
                for name, font_ref in fonts.items():
                    key = str(name)
                    if key in seen:
                        continue
                    seen.add(key)
                    font = resolve1(font_ref) or {}
                    descriptor = resolve1(font.get("FontDescriptor")) if font.get("FontDescriptor") else {}
                    embedded = "no"
                    if descriptor and any(
                        descriptor.get(item) is not None
                        for item in ("FontFile", "FontFile2", "FontFile3")
                    ):
                        embedded = "yes"
                    unicode_ok = "yes" if font.get("ToUnicode") is not None else "no"
                    rows.append({"embedded": embedded, "unicode": unicode_ok})
    except Exception:
        return []
    return rows


def _normalized(value: str) -> str:
    return "".join(str(value or "").split())
