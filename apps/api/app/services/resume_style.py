import re

from app.services.resume_template import SECTION_ORDER

PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297
MARGIN_VERTICAL_MM = 18
MARGIN_HORIZONTAL_MM = 16

BODY_CJK_FONT = "微软雅黑"
BODY_LATIN_FONT = "Calibri"
HEADING_CJK_FONT = "黑体"
BODY_SIZE_PT = 10.5
SECTION_SIZE_PT = 12
NAME_SIZE_PT = 22
LINE_SPACING = 1.15

INK_HEX = "1F2933"
ACCENT_HEX = "2F3E63"
MUTED_HEX = "5B6575"
BORDER_HEX = "2F3E63"
BACKGROUND_HEX = "ECEBE6"
UNACHIEVED_LABEL = "[未达成 · 学习目标]"
BLUEPRINT_MARK = "*"
BLUEPRINT_FOOTER = "* 为目标蓝图内容，尚未形成可核验经历"
SKILL_SECTION_NAME = "技能证书"
ENTRY_SEPARATOR = "｜"
CONTACT_LABELS = (("phone", "电话"), ("email", "邮箱"), ("city", "城市"))


def is_v3(content: dict | None) -> bool:
    return int((content or {}).get("content_version") or 0) >= 3


def unachieved_mark(content: dict | None) -> str:
    return BLUEPRINT_MARK if is_v3(content) else UNACHIEVED_LABEL


def should_mark_unachieved(content: dict | None, bullet: dict | None) -> bool:
    """Only blueprint gaps get a visible asterisk.

    The marker belongs to the blueprint, whose gaps are the point of that
    document. The submittable resume is the version a candidate sends to an
    employer, so it must not carry an unachieved marker at all: an AI-expanded
    line there keeps its internal provenance status without a visible label.
    """
    if not isinstance(bullet, dict) or bullet.get("achieved") is not False:
        return False
    if (content or {}).get("kind") != "target":
        return False
    if (
        (content or {}).get("factuality_policy") == "ai_expansion"
        and bullet.get("verification_status") == "ai_generated"
        and not (bullet.get("source_target_ids") or bullet.get("requirement_ids"))
    ):
        return False
    return True


def has_unachieved_bullets(content: dict | None) -> bool:
    for section in (content or {}).get("sections") or []:
        for item in section.get("items") or []:
            for bullet in item.get("bullets") or []:
                if should_mark_unachieved(content, bullet):
                    return True
    return False


def blueprint_footer(content: dict | None) -> str:
    if (content or {}).get("kind") != "target" or not is_v3(content):
        return ""
    if not has_unachieved_bullets(content):
        return ""
    return BLUEPRINT_FOOTER


def is_skill_tag_section(section) -> bool:
    if not isinstance(section, dict):
        return False
    return section.get("presentation") == "tags" or section.get("name") in {
        SKILL_SECTION_NAME,
        "技能",
    }


def spaced_cjk_name(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text):
        return " ".join(text)
    return str(value or "").strip()


def format_resume_date(value: str) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", text)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return text


def format_entry_headline(item: dict, *, education: bool = False) -> str:
    organization = str(item.get("organization") or "").strip()
    role_title = str(item.get("role_title") or "").strip()
    start = format_resume_date(str(item.get("start_date") or ""))
    end = format_resume_date(str(item.get("end_date") or ""))
    dates = "–".join(part for part in (start, end) if part)
    parts = [organization, role_title, dates] if education else [role_title, organization, dates]
    return ENTRY_SEPARATOR.join(part for part in parts if part)


def labeled_contact_parts(contact: dict | None) -> list[str]:
    values = contact if isinstance(contact, dict) else {}
    return [
        f"{label}：{values.get(field)}"
        for field, label in CONTACT_LABELS
        if values.get(field)
    ]


def resolved_style(snapshot: dict | None = None) -> dict:
    snap = snapshot or {}
    page = snap.get("page") or {}
    colors = snap.get("colors") or {}
    typography = snap.get("typography") or {}
    return {
        "page_width_mm": page.get("width_mm") or PAGE_WIDTH_MM,
        "page_height_mm": page.get("height_mm") or PAGE_HEIGHT_MM,
        "margin_horizontal_mm": page.get("margin_horizontal_mm") or MARGIN_HORIZONTAL_MM,
        "margin_vertical_mm": page.get("margin_vertical_mm") or MARGIN_VERTICAL_MM,
        "cjk_font": typography.get("cjk_font") or BODY_CJK_FONT,
        "heading_cjk": typography.get("heading_cjk_font") or HEADING_CJK_FONT,
        "latin_font": typography.get("latin_font") or BODY_LATIN_FONT,
        "name_size_pt": typography.get("name_size_pt") or NAME_SIZE_PT,
        "section_size_pt": typography.get("section_size_pt") or SECTION_SIZE_PT,
        "body_size_pt": typography.get("body_size_pt") or BODY_SIZE_PT,
        "line_spacing": typography.get("line_spacing") or LINE_SPACING,
        "ink_hex": str(colors.get("ink") or INK_HEX),
        "accent_hex": str(colors.get("accent") or ACCENT_HEX),
        "muted_hex": str(colors.get("muted") or MUTED_HEX),
        "border_hex": str(colors.get("border") or BORDER_HEX),
        "background_hex": str(colors.get("background") or BACKGROUND_HEX),
    }


def header_copy(content: dict | None, fallback_title: str) -> dict:
    payload = content or {}
    contact = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    headline = str(payload.get("headline") or fallback_title or "").strip()
    name = str(contact.get("name") or "").strip()
    subtitle = f"意向：{headline}" if name and headline and headline != name else ""
    return {
        "display_name": spaced_cjk_name(name or headline or fallback_title),
        "subtitle": subtitle,
        "contact_parts": labeled_contact_parts(contact),
        "headline": headline,
        "contact": contact,
    }


def is_education_section(section) -> bool:
    return isinstance(section, dict) and str(section.get("name") or "") == "教育背景"


def ordered_visible_sections(content: dict | None, snapshot: dict | None = None) -> list[dict]:
    """Apply the template section order and drop empty partitions at render time."""
    sections = [
        section
        for section in (content or {}).get("sections") or []
        if isinstance(section, dict)
    ]
    layout = (snapshot or {}).get("layout") or {}
    names = [str(name) for name in (layout.get("section_order") or SECTION_ORDER) if name]
    order = {name: index for index, name in enumerate(names)}
    ordered = sorted(
        sections,
        key=lambda section: (
            0 if str(section.get("name") or "") in order else 1,
            order.get(str(section.get("name") or ""), 0),
        ),
    )
    if layout.get("hide_empty_sections") is False:
        return ordered
    return [section for section in ordered if _section_has_items(section)]


def _section_has_items(section: dict) -> bool:
    items = section.get("items") if isinstance(section.get("items"), list) else []
    return any(isinstance(item, dict) for item in items)
