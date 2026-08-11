import io

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .resume_style import (
    ACCENT_HEX,
    BODY_CJK_FONT,
    BODY_LATIN_FONT,
    BODY_SIZE_PT,
    HEADING_CJK_FONT,
    INK_HEX,
    LINE_SPACING,
    MARGIN_HORIZONTAL_MM,
    MARGIN_VERTICAL_MM,
    MUTED_HEX,
    NAME_SIZE_PT,
    PAGE_HEIGHT_MM,
    PAGE_WIDTH_MM,
    SECTION_SIZE_PT,
    UNACHIEVED_LABEL,
)

INK = RGBColor.from_string(INK_HEX)
ACCENT = RGBColor.from_string(ACCENT_HEX)
MUTED = RGBColor.from_string(MUTED_HEX)


def _set_style_font(
    style,
    *,
    size: float,
    color: RGBColor,
    bold: bool = False,
    cjk_font: str = BODY_CJK_FONT,
) -> None:
    style.font.name = BODY_LATIN_FONT
    style.font.size = Pt(size)
    style.font.color.rgb = color
    style.font.bold = bold
    style._element.rPr.rFonts.set(qn("w:ascii"), BODY_LATIN_FONT)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), BODY_LATIN_FONT)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), cjk_font)


def render_resume_docx(content: dict, fallback_title: str) -> bytes:
    """Render v1 or v2 resume content as a deterministic A4 Word document."""
    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(PAGE_WIDTH_MM)
    section.page_height = Mm(PAGE_HEIGHT_MM)
    section.top_margin = Mm(MARGIN_VERTICAL_MM)
    section.right_margin = Mm(MARGIN_HORIZONTAL_MM)
    section.bottom_margin = Mm(MARGIN_VERTICAL_MM)
    section.left_margin = Mm(MARGIN_HORIZONTAL_MM)
    section.header_distance = Mm(8)
    section.footer_distance = Mm(8)

    _configure_styles(doc)
    contact = content.get("contact") if isinstance(content.get("contact"), dict) else {}
    headline = str(content.get("headline") or fallback_title)
    display_name = str(contact.get("name") or headline)
    title = doc.add_paragraph(style="Resume Name")
    title.add_run(display_name)
    if contact.get("name") and headline != display_name:
        subtitle = doc.add_paragraph(style="Resume Subtitle")
        subtitle.add_run(headline)
    contact_text = " · ".join(
        str(contact.get(field) or "") for field in ("phone", "email", "city") if contact.get(field)
    )
    if contact_text:
        paragraph = doc.add_paragraph(style="Resume Contact")
        paragraph.add_run(contact_text)

    for value in content.get("sections") or []:
        if not isinstance(value, dict):
            continue
        items = value.get("items") if isinstance(value.get("items"), list) else []
        if not items:
            continue
        doc.add_paragraph(str(value.get("name") or "经历"), style="Resume Section")
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("bullets"), list):
                _render_v2_item(doc, item)
            elif item.get("text"):
                _add_bullet(doc, str(item.get("text") or ""), achieved=True)

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    _set_style_font(normal, size=BODY_SIZE_PT, color=INK)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = LINE_SPACING

    name = doc.styles.add_style("Resume Name", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(
        name,
        size=NAME_SIZE_PT,
        color=INK,
        bold=True,
        cjk_font=HEADING_CJK_FONT,
    )
    name.paragraph_format.space_after = Pt(3)
    name.paragraph_format.keep_with_next = True

    subtitle = doc.styles.add_style("Resume Subtitle", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(
        subtitle,
        size=SECTION_SIZE_PT,
        color=ACCENT,
        bold=True,
        cjk_font=HEADING_CJK_FONT,
    )
    subtitle.paragraph_format.space_after = Pt(2)

    contact = doc.styles.add_style("Resume Contact", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(contact, size=9.5, color=MUTED)
    contact.paragraph_format.space_after = Pt(7)
    contact.paragraph_format.keep_with_next = True

    heading = doc.styles.add_style("Resume Section", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(
        heading,
        size=SECTION_SIZE_PT,
        color=ACCENT,
        bold=True,
        cjk_font=HEADING_CJK_FONT,
    )
    heading.paragraph_format.space_before = Pt(7)
    heading.paragraph_format.space_after = Pt(3)
    heading.paragraph_format.keep_with_next = True

    entry = doc.styles.add_style("Resume Entry Header", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(entry, size=BODY_SIZE_PT, color=INK, bold=True)
    entry.paragraph_format.space_before = Pt(2)
    entry.paragraph_format.space_after = Pt(1)
    entry.paragraph_format.keep_with_next = True
    entry.paragraph_format.tab_stops.add_tab_stop(Mm(173), WD_TAB_ALIGNMENT.RIGHT)

    bullet = doc.styles.add_style("Resume Bullet", WD_STYLE_TYPE.PARAGRAPH)
    bullet.base_style = doc.styles["List Bullet"]
    _set_style_font(bullet, size=BODY_SIZE_PT, color=INK)
    bullet.paragraph_format.left_indent = Mm(5)
    bullet.paragraph_format.first_line_indent = Mm(-3)
    bullet.paragraph_format.space_after = Pt(2)
    bullet.paragraph_format.line_spacing = LINE_SPACING
    bullet.paragraph_format.keep_together = True


def _render_v2_item(doc: Document, item: dict) -> None:
    left = " — ".join(
        value
        for value in (str(item.get("organization") or ""), str(item.get("role_title") or ""))
        if value
    )
    dates = " – ".join(
        value
        for value in (str(item.get("start_date") or ""), str(item.get("end_date") or ""))
        if value
    )
    if left or dates:
        header = doc.add_paragraph(style="Resume Entry Header")
        header.add_run(left)
        if dates:
            header.add_run("\t")
            header.add_run(dates)
    for bullet in item.get("bullets") or []:
        if isinstance(bullet, dict):
            _add_bullet(
                doc,
                str(bullet.get("text") or ""),
                achieved=bullet.get("achieved") is not False,
            )


def _add_bullet(doc: Document, text: str, *, achieved: bool) -> None:
    paragraph = doc.add_paragraph(style="Resume Bullet")
    if not achieved:
        label = paragraph.add_run(f"{UNACHIEVED_LABEL} ")
        label.font.color.rgb = MUTED
        value = paragraph.add_run(text)
        value.font.color.rgb = MUTED
    else:
        paragraph.add_run(text)
