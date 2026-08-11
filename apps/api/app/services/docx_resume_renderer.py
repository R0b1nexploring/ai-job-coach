import io

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

INK = RGBColor(0x0B, 0x25, 0x45)
HEADING = RGBColor(0x2E, 0x74, 0xB5)
LATIN_FONT = "Arial Unicode MS"
CJK_FONT = "Arial Unicode MS"


def _set_style_font(style, *, size: float, color: RGBColor, bold: bool = False) -> None:
    style.font.name = LATIN_FONT
    style.font.size = Pt(size)
    style.font.color.rgb = color
    style.font.bold = bold
    style._element.rPr.rFonts.set(qn("w:ascii"), LATIN_FONT)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), LATIN_FONT)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)


def render_resume_docx(content: dict, fallback_title: str) -> bytes:
    """Render a compact, deterministic resume without changing any content facts."""
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.right_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    normal = doc.styles["Normal"]
    _set_style_font(normal, size=11, color=INK)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    heading = doc.styles["Heading 1"]
    _set_style_font(heading, size=16, color=HEADING, bold=True)
    heading.paragraph_format.space_before = Pt(18)
    heading.paragraph_format.space_after = Pt(10)
    heading.paragraph_format.keep_with_next = True

    title_style = doc.styles.add_style("Resume Title", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(title_style, size=20, color=INK, bold=True)
    title_style.paragraph_format.space_before = Pt(0)
    title_style.paragraph_format.space_after = Pt(12)
    title_style.paragraph_format.line_spacing = 1.0
    title_style.paragraph_format.keep_with_next = True

    entry_style = doc.styles.add_style("Resume Entry", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(entry_style, size=11, color=INK)
    entry_style.paragraph_format.space_before = Pt(0)
    entry_style.paragraph_format.space_after = Pt(4)
    entry_style.paragraph_format.line_spacing = 1.25
    entry_style.paragraph_format.keep_together = True

    title = doc.add_paragraph(style="Resume Title")
    title.add_run(content.get("headline") or fallback_title)
    for value in content.get("sections", []):
        doc.add_paragraph(value.get("name") or "经历", style="Heading 1")
        for item in value.get("items", []):
            paragraph = doc.add_paragraph(style="Resume Entry")
            paragraph.add_run(item.get("text", ""))

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
