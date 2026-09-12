"""PDF export with Chromium first, LibreOffice fallback, and physical QA."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

from app.errors import AppError
from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html
from app.services.resume_style import (
    blueprint_footer,
    format_entry_headline,
    header_copy,
    is_education_section,
    ordered_visible_sections,
)

A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89


async def export_pdf(content: dict, title: str, snapshot: dict | None = None) -> bytes:
    pdf, qa = await _render_pdf_attempt(content, title, snapshot)
    if pdf is None:
        raise AppError(
            "PDF_CONVERTER_UNAVAILABLE",
            "当前环境没有可用的 Chromium 或 LibreOffice，无法导出 PDF。HTML 和 DOCX 仍可下载。",
            503,
        )
    if qa["status"] == "passed":
        return pdf
    if _is_page_overflow(qa["issues"]):
        compact = compact_spacing_snapshot(snapshot)
        if compact is not None:
            compact_pdf, compact_qa = await _render_pdf_attempt(content, title, compact)
            if compact_pdf is not None and compact_qa["status"] == "passed":
                return compact_pdf
            if compact_pdf is not None:
                qa = compact_qa
    failure_kind = classify_pdf_issues(qa["issues"])
    message = (
        "PDF 超出单页，已拒绝该文件。请在内容阶段缩写未锁定要点。"
        if failure_kind == "content_overflow"
        else "PDF 未通过字体、Unicode、裁切或文本层检查，请重试导出，不会改写简历正文。"
    )
    raise AppError(
        "PDF_QA_FAILED",
        message,
        422,
        details={"issues": qa["issues"], "failure_kind": failure_kind},
    )


async def _render_pdf_attempt(content: dict, title: str, snapshot: dict | None) -> tuple[bytes | None, dict]:
    html = render_resume_html(content, title, snapshot=snapshot)
    pdf = await _chromium_pdf(html)
    if pdf is None:
        pdf = await asyncio.to_thread(_libreoffice_pdf, content, title, snapshot)
    if pdf is None:
        return None, {"status": "failed", "issues": ["converter_unavailable"]}
    return pdf, inspect_pdf_bytes(pdf, content)


def compact_spacing_snapshot(snapshot: dict | None) -> dict | None:
    snap = deepcopy(snapshot or {})
    typography = dict(snap.get("typography") or {})
    current = float(typography.get("line_spacing") or 1.15)
    minimum = float(typography.get("line_spacing_min") or 1.0)
    if current <= minimum:
        return None
    typography["line_spacing"] = minimum
    snap["typography"] = typography
    return snap


def classify_pdf_issues(issues: list[str]) -> str:
    text = " ".join(str(item) for item in issues)
    technical_markers = ("fonts:", "crop:", "unicode", "converter")
    if _is_page_overflow(issues) and not any(marker in text for marker in technical_markers):
        return "content_overflow"
    if _is_page_overflow(issues):
        return "content_overflow"
    return "technical"


def _is_page_overflow(issues: list[str]) -> bool:
    return any("page_count" in str(item) for item in issues)


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
        for label, value in _expected_visible_text(content):
            if _normalized(value) not in normalized:
                issues.append(f"text:{label}: not visible in PDF text layer")
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


def _expected_visible_text(content: dict) -> list[tuple[str, str]]:
    """Describe every user-visible text fragment without echoing PII in errors."""
    expected: list[tuple[str, str]] = []
    header = header_copy(content, "简历")
    if header.get("display_name"):
        expected.append(("header_name", str(header["display_name"])))
    if header.get("subtitle"):
        expected.append(("header_subtitle", str(header["subtitle"])))
    for part in header.get("contact_parts") or []:
        if str(part).strip():
            expected.append(("contact", str(part)))

    gap = content.get("gap_summary") if isinstance(content.get("gap_summary"), dict) else {}
    if content.get("kind") == "target" and gap.get("reasons"):
        expected.append(("gap_title", str(gap.get("title") or "对照岗位还缺什么")))
        for reason in gap.get("reasons") or []:
            if str(reason).strip():
                expected.append(("gap_reason", str(reason)))

    for section in ordered_visible_sections(content):
        name = str(section.get("name") or "")
        if name:
            expected.append(("section", name))
        education = is_education_section(section)
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            headline = format_entry_headline(item, education=education)
            if headline:
                expected.append(("entry_headline", headline))
            if isinstance(item.get("bullets"), list):
                for bullet in item.get("bullets") or []:
                    value = str((bullet or {}).get("text") or "").strip()
                    if value:
                        expected.append(("bullet", value))
            else:
                value = str(item.get("text") or "").strip()
                if value:
                    expected.append(("item", value))
    footer = blueprint_footer(content)
    if footer:
        expected.append(("blueprint_footer", footer))
    return expected
