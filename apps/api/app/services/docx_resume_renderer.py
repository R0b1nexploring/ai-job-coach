import io

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
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
    format_entry_headline,
    is_skill_tag_section,
    labeled_contact_parts,
    spaced_cjk_name,
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
    display_name = spaced_cjk_name(str(contact.get("name") or headline))
    title = doc.add_paragraph(style="Resume Name")
    title.add_run(display_name)
    contact_parts = labeled_contact_parts(contact)
    if contact_parts:
        paragraph = doc.add_paragraph(style="Resume Contact")
        paragraph.add_run("    ".join(contact_parts))
    if contact.get("name") and headline and headline != str(contact.get("name") or ""):
        subtitle = doc.add_paragraph(style="Resume Subtitle")
        subtitle.add_run(f"意向：{headline}")

    gap = content.get("gap_summary") if isinstance(content.get("gap_summary"), dict) else {}
    if content.get("kind") == "target" and gap.get("reasons"):
        doc.add_paragraph(str(gap.get("title") or "对照岗位还缺什么"), style="Resume Section")
        intro = doc.add_paragraph(style="Resume Contact")
        intro.add_run("未达成条目按 JD 列出，不是已经做过的经历。")
        for reason in gap.get("reasons") or []:
            _add_bullet(doc, str(reason), achieved=True)

    for value in content.get("sections") or []:
        if not isinstance(value, dict):
            continue
        items = value.get("items") if isinstance(value.get("items"), list) else []
        if not items:
            continue
        heading = doc.add_paragraph(str(value.get("name") or "经历"), style="Resume Section")
        _set_bottom_border(heading)
        if is_skill_tag_section(value):
            _render_skill_tags(doc, items)
            continue
        education = str(value.get("name") or "") == "教育背景"
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("bullets"), list):
                _render_v2_item(doc, item, education=education)
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
        color=ACCENT,
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
    _set_style_font(contact, size=9.5, color=INK)
    contact.paragraph_format.space_after = Pt(4)
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

    skills = doc.styles.add_style("Resume Skills", WD_STYLE_TYPE.PARAGRAPH)
    _set_style_font(skills, size=BODY_SIZE_PT, color=INK)
    skills.paragraph_format.space_after = Pt(3)
    skills.paragraph_format.line_spacing = LINE_SPACING


def _render_skill_tags(doc: Document, items: list) -> None:
    parts = []
    muted_indexes = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for bullet in item.get("bullets") or []:
            if not isinstance(bullet, dict):
                continue
            text = str(bullet.get("text") or "").strip()
            if not text:
                continue
            if bullet.get("achieved") is False:
                muted_indexes.add(len(parts))
                text = f"{UNACHIEVED_LABEL} {text}"
            parts.append(text)
    if not parts:
        return
    paragraph = doc.add_paragraph(style="Resume Skills")
    for index, part in enumerate(parts):
        if index:
            paragraph.add_run(" / ")
        run = paragraph.add_run(part)
        if index in muted_indexes:
            run.font.color.rgb = MUTED


def _set_bottom_border(paragraph) -> None:
    paragraph_properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), ACCENT_HEX)
    borders.append(bottom)
    paragraph_properties.append(borders)


def _render_v2_item(doc: Document, item: dict, *, education: bool = False) -> None:
    headline = format_entry_headline(item, education=education)
    if headline:
        header = doc.add_paragraph(style="Resume Entry Header")
        header.add_run(headline)
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
