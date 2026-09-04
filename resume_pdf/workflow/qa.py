from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .renderer import UNACHIEVED_LABEL

A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89


def inspect_pdf(pdf_path: Path, content: dict, preview_dir: Path) -> dict:
    issues: list[str] = []
    preview_dir.mkdir(parents=True, exist_ok=True)
    page_count, width, height = _pdf_geometry(pdf_path)
    if page_count != 1:
        issues.append(f"page_count: expected 1, got {page_count}")
    if abs(width - A4_WIDTH_PT) > 2 or abs(height - A4_HEIGHT_PT) > 2:
        issues.append("page_size: expected A4 portrait")
    extracted = _pdf_text(pdf_path)

    normalized_pdf = _normalized(extracted)
    expected_target_count = 0
    expected_fragments: list[tuple[str, str]] = []
    for section_index, section in enumerate(content.get("sections") or []):
        expected_fragments.append((f"sections.{section_index}.name", str(section.get("name") or "")))
        for item_index, item in enumerate(section.get("items") or []):
            for bullet_index, bullet in enumerate(item.get("bullets") or []):
                pointer = f"sections.{section_index}.items.{item_index}.bullets.{bullet_index}.text"
                expected_fragments.append((pointer, str(bullet.get("text") or "")))
                if bullet.get("achieved") is False:
                    expected_target_count += 1
    for pointer, value in expected_fragments:
        if value and _normalized(value) not in normalized_pdf:
            issues.append(f"{pointer}: not visible in PDF text layer")
    actual_target_count = normalized_pdf.count(_normalized(UNACHIEVED_LABEL))
    if actual_target_count != expected_target_count:
        issues.append(
            f"unachieved_marker: expected {expected_target_count}, got {actual_target_count}"
        )

    font_rows = _font_rows(pdf_path)
    if not font_rows:
        issues.append("fonts: no fonts detected")
    elif any(row["embedded"] != "yes" for row in font_rows):
        issues.append("fonts: every font must be embedded")
    elif any(row["unicode"] != "yes" for row in font_rows):
        issues.append("fonts: every font must include a Unicode map")

    prefix = preview_dir / pdf_path.stem
    rendered = subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-r", "144", "-png", str(pdf_path), str(prefix)],
        capture_output=True,
        text=True,
        check=False,
    )
    preview_path = prefix.with_suffix(".png")
    if rendered.returncode != 0 or not preview_path.exists():
        issues.append("preview: pdftoppm rendering failed")

    return {
        "status": "passed" if not issues else "failed",
        "artifact": pdf_path.name,
        "checks": {
            "page_count": page_count,
            "page_width_pt": round(width, 2),
            "page_height_pt": round(height, 2),
            "font_count": len(font_rows),
            "all_fonts_embedded": bool(font_rows)
            and all(row["embedded"] == "yes" for row in font_rows),
            "all_fonts_unicode": bool(font_rows)
            and all(row["unicode"] == "yes" for row in font_rows),
            "unachieved_markers": actual_target_count,
            "preview_created": preview_path.exists(),
        },
        "issues": issues,
    }


def _font_rows(pdf_path: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["pdffonts", str(pdf_path)],
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
    return rows


def _pdf_geometry(pdf_path: Path) -> tuple[int, float, float]:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    pages = re.search(r"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    size = re.search(
        r"^Page size:\s+([\d.]+) x ([\d.]+) pts",
        result.stdout,
        re.MULTILINE,
    )
    if not pages or not size:
        raise RuntimeError("Unable to inspect PDF geometry")
    return int(pages.group(1)), float(size.group(1)), float(size.group(2))


def _pdf_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Unable to inspect PDF text layer")
    return result.stdout


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))
