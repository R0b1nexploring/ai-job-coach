import re

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
SKILL_SECTION_NAME = "技能证书"
ENTRY_SEPARATOR = "｜"
CONTACT_LABELS = (("phone", "电话"), ("email", "邮箱"), ("city", "城市"))


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
