from html import escape
from string import Template

from .resume_style import (
    ACCENT_HEX,
    BACKGROUND_HEX,
    BODY_CJK_FONT,
    BODY_LATIN_FONT,
    BODY_SIZE_PT,
    BORDER_HEX,
    HEADING_CJK_FONT,
    INK_HEX,
    MARGIN_HORIZONTAL_MM,
    MARGIN_VERTICAL_MM,
    MUTED_HEX,
    NAME_SIZE_PT,
    PAGE_HEIGHT_MM,
    PAGE_WIDTH_MM,
    SECTION_SIZE_PT,
    UNACHIEVED_LABEL,
)


def _text(value) -> str:
    return escape(str(value or ""), quote=True)


def render_resume_html(content: dict, title: str) -> str:
    """Render v1 or v2 resume content as a self-contained escaped A4 page."""
    headline = _text(content.get("headline") or title)
    contact = content.get("contact") if isinstance(content.get("contact"), dict) else {}
    display_name = _text(contact.get("name") or content.get("headline") or title)
    contact_text = " · ".join(
        _text(contact.get(field)) for field in ("phone", "email", "city") if contact.get(field)
    )
    subtitle = f'<p class="subtitle">{headline}</p>' if contact.get("name") else ""
    contact_html = f'<p class="contact">{contact_text}</p>' if contact_text else ""
    sections_html: list[str] = []
    sections = content.get("sections", [])
    if not isinstance(sections, list):
        sections = []
    for section in sections:
        rendered = _render_section(section)
        if rendered:
            sections_html.append(rendered)
    body = "".join(sections_html) or '<p class="empty">暂无可导出的已审核内容。</p>'
    css = _style_css()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{headline}</title>
<style>
{css}
</style>
</head>
<body>
<main class="page"><header><h1>{display_name}</h1>{subtitle}{contact_html}</header>{body}</main>
</body>
</html>"""


def _style_css() -> str:
    return Template(
        """
*{box-sizing:border-box}html,body{margin:0;padding:0}
body{background:#$background;color:#$ink;font-family:"$latin","$cjk",sans-serif;font-size:${body_size}pt;line-height:1.15}
.page{width:${page_width}mm;min-height:${page_height}mm;margin:18px auto;background:#fff;padding:${margin_vertical}mm ${margin_horizontal}mm;box-shadow:0 2px 16px #0002}
header{border-bottom:1px solid #$border;padding-bottom:7px;margin-bottom:8px}
h1{font-family:"$latin","$heading_cjk",sans-serif;font-size:${name_size}pt;line-height:1.2;margin:0;color:#$ink}
.subtitle{font-family:"$latin","$heading_cjk",sans-serif;font-size:${section_size}pt;font-weight:700;color:#$accent;margin:3px 0 0}
.contact{color:#$muted;font-size:9.5pt;margin:3px 0 0}
section{margin:0 0 7px;break-inside:avoid}
h2{font-family:"$latin","$heading_cjk",sans-serif;font-size:${section_size}pt;margin:0 0 4px;border-bottom:1px solid #$border;padding-bottom:2px;color:#$accent}
.entry{margin:0 0 4px;break-inside:avoid}.entry-head{display:flex;justify-content:space-between;gap:12px;font-weight:700;margin:0 0 2px}.dates{white-space:nowrap}
ul{margin:0;padding:0;list-style:none}li{position:relative;padding-left:13px;margin:0 0 2px}li::before{content:"•";position:absolute;left:1px;color:#$accent}
li.unachieved,li.unachieved::before{color:#$muted}.target-label{font-weight:700}.empty{color:#$muted}
@page{size:A4;margin:0}@media print{body{background:#fff}.page{margin:0;box-shadow:none}}
"""
    ).substitute(
        background=BACKGROUND_HEX,
        ink=INK_HEX,
        latin=BODY_LATIN_FONT,
        cjk=BODY_CJK_FONT,
        heading_cjk=HEADING_CJK_FONT,
        body_size=BODY_SIZE_PT,
        page_width=PAGE_WIDTH_MM,
        page_height=PAGE_HEIGHT_MM,
        margin_vertical=MARGIN_VERTICAL_MM,
        margin_horizontal=MARGIN_HORIZONTAL_MM,
        border=BORDER_HEX,
        name_size=NAME_SIZE_PT,
        section_size=SECTION_SIZE_PT,
        accent=ACCENT_HEX,
        muted=MUTED_HEX,
    ).strip()


def _render_section(section) -> str:
    if not isinstance(section, dict):
        return ""
    name = _text(section.get("name") or "相关经历")
    items = section.get("items") if isinstance(section.get("items"), list) else []
    items_html = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("bullets"), list):
            rendered = _render_v2_item(item)
        else:
            value = _text(item.get("text"))
            rendered = f'<div class="entry"><ul><li>{value}</li></ul></div>' if value else ""
        if rendered:
            items_html.append(rendered)
    if not items_html:
        return ""
    return f'<section data-resume-section="true"><h2>{name}</h2>{"".join(items_html)}</section>'


def _render_v2_item(item: dict) -> str:
    organization = _text(item.get("organization"))
    role_title = _text(item.get("role_title"))
    left = " — ".join(value for value in (organization, role_title) if value)
    dates = " – ".join(
        _text(item.get(field)) for field in ("start_date", "end_date") if item.get(field)
    )
    head = (
        f'<p class="entry-head"><span>{left}</span><span class="dates">{dates}</span></p>'
        if left or dates
        else ""
    )
    bullets_html = []
    for bullet in item.get("bullets") or []:
        if not isinstance(bullet, dict):
            continue
        value = _text(bullet.get("text"))
        if not value:
            continue
        if bullet.get("achieved") is False:
            value = f'<span class="target-label">{_text(UNACHIEVED_LABEL)}</span> {value}'
            bullets_html.append(f'<li class="unachieved">{value}</li>')
        else:
            bullets_html.append(f"<li>{value}</li>")
    return f'<div class="entry">{head}<ul>{"".join(bullets_html)}</ul></div>' if bullets_html else ""
