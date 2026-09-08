from html import escape
from string import Template

from .resume_style import (
    blueprint_footer,
    format_entry_headline,
    header_copy,
    is_education_section,
    is_skill_tag_section,
    ordered_visible_sections,
    resolved_style,
    should_mark_unachieved,
    unachieved_mark,
)


def _text(value) -> str:
    return escape(str(value or ""), quote=True)


def render_resume_html(content: dict, title: str, snapshot: dict | None = None) -> str:
    """Render v1 or v2 resume content as a self-contained escaped A4 page."""
    header = header_copy(content, title)
    display_name = _text(header["display_name"])
    contact_html = (
        '<p class="contact">'
        + "".join(f"<span>{_text(part)}</span>" for part in header["contact_parts"])
        + "</p>"
        if header["contact_parts"]
        else ""
    )
    subtitle = (
        f'<p class="subtitle">{_text(header["subtitle"])}</p>' if header["subtitle"] else ""
    )
    gap = content.get("gap_summary") if isinstance(content.get("gap_summary"), dict) else {}
    gap_html = ""
    if content.get("kind") == "target" and gap.get("reasons"):
        reason_items = "".join(f"<li>{_text(reason)}</li>" for reason in gap.get("reasons") or [])
        gap_html = (
            '<aside class="gap-summary"><h2>'
            f'{_text(gap.get("title") or "对照岗位还缺什么")}</h2>'
            '<p>未达成条目按 JD 列出，不是已经做过的经历。</p>'
            f"<ul>{reason_items}</ul></aside>"
        )
    sections_html: list[str] = []
    mark = unachieved_mark(content)
    for section in ordered_visible_sections(content, snapshot):
        rendered = _render_section(section, mark=mark, content=content)
        if rendered:
            sections_html.append(rendered)
    body = "".join(sections_html) or '<p class="empty">暂无可导出的已审核内容。</p>'
    footer_text = blueprint_footer(content)
    footer_html = (
        f'<p class="blueprint-footer">{_text(footer_text)}</p>' if footer_text else ""
    )
    css = _style_css(snapshot)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_text(header["headline"] or title)}</title>
<style>
{css}
</style>
</head>
<body>
<main class="page"><header><h1>{display_name}</h1>{subtitle}{contact_html}</header>{gap_html}{body}{footer_html}</main>
</body>
</html>"""


def _style_css(snapshot: dict | None = None) -> str:
    style = resolved_style(snapshot)
    return Template(
        """
*{box-sizing:border-box}html,body{margin:0;padding:0}
body{background:#$background;color:#$ink;font-family:"$latin","$cjk",sans-serif;font-size:${body_size}pt;line-height:${line_height}}
.page{width:${page_width}mm;min-height:${page_height}mm;margin:18px auto;background:#fff;padding:${margin_vertical}mm ${margin_horizontal}mm;box-shadow:0 2px 16px #0002}
header{border-bottom:0;padding-bottom:8px;margin-bottom:10px}
h1{font-family:"$latin","$heading_cjk",sans-serif;font-size:${name_size}pt;line-height:1.2;margin:0;color:#$accent;letter-spacing:0.08em}
.subtitle{font-family:"$latin","$heading_cjk",sans-serif;font-size:11pt;font-weight:700;color:#$accent;margin:6px 0 0}
.contact{color:#$ink;font-size:9.5pt;margin:6px 0 0;display:flex;flex-wrap:wrap;gap:18px 28px}
.contact span{white-space:nowrap}
section{margin:0 0 8px;break-inside:avoid}
h2{font-family:"$latin","$heading_cjk",sans-serif;font-size:${section_size}pt;margin:0 0 5px;border-bottom:1.5px solid #$border;padding-bottom:3px;color:#$accent}
.entry{margin:0 0 5px;break-inside:avoid}.entry-head{font-weight:700;margin:0 0 2px}
ul{margin:0;padding:0;list-style:none}li{position:relative;padding-left:13px;margin:0 0 2px}li::before{content:"•";position:absolute;left:1px;color:#$accent}
li.unachieved,li.unachieved::before{color:#$muted}.target-label{font-weight:700;font-size:0.85em;vertical-align:super}.empty{color:#$muted}.blueprint-footer{margin-top:10px;font-size:9pt;color:#$muted}
.skill-tags{margin:0;line-height:1.4}.skill-tags .unachieved{color:#$muted}
.gap-summary{background:#f8f1e3;border:1px solid #$border;padding:6px 8px;margin:0 0 8px;font-size:9.5pt}
.gap-summary h2{border:0;margin:0 0 3px;padding:0}.gap-summary p{margin:0 0 4px;color:#$muted}
@page{size:A4;margin:0}@media print{body{background:#fff}.page{margin:0;box-shadow:none}}
"""
    ).substitute(
        background=style["background_hex"],
        ink=style["ink_hex"],
        latin=style["latin_font"],
        cjk=style["cjk_font"],
        heading_cjk=style["heading_cjk"],
        body_size=style["body_size_pt"],
        page_width=style["page_width_mm"],
        page_height=style["page_height_mm"],
        margin_vertical=style["margin_vertical_mm"],
        margin_horizontal=style["margin_horizontal_mm"],
        border=style["border_hex"],
        name_size=style["name_size_pt"],
        section_size=style["section_size_pt"],
        accent=style["accent_hex"],
        muted=style["muted_hex"],
        line_height=style["line_spacing"],
    ).strip()


def _render_section(section, *, mark: str, content: dict | None = None) -> str:
    if not isinstance(section, dict):
        return ""
    name = _text(section.get("name") or "相关经历")
    items = section.get("items") if isinstance(section.get("items"), list) else []
    items_html = []
    if is_skill_tag_section(section):
        rendered = _render_skill_tags(items, mark=mark, content=content)
        if rendered:
            items_html.append(rendered)
    else:
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("bullets"), list):
                rendered = _render_v2_item(
                    item,
                    education=is_education_section(section),
                    mark=mark,
                    content=content,
                )
            else:
                value = _text(item.get("text"))
                rendered = f'<div class="entry"><ul><li>{value}</li></ul></div>' if value else ""
            if rendered:
                items_html.append(rendered)
    if not items_html:
        return ""
    return f'<section data-resume-section="true"><h2>{name}</h2>{"".join(items_html)}</section>'


def _render_skill_tags(items: list, *, mark: str, content: dict | None = None) -> str:
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for bullet in item.get("bullets") or []:
            if not isinstance(bullet, dict):
                continue
            raw = str(bullet.get("text") or "").strip()
            if not raw:
                continue
            value = _text(raw)
            if should_mark_unachieved(content, bullet):
                value = f'{value}<span class="target-label">{_text(mark)}</span>'
                parts.append(f'<span class="unachieved">{value}</span>')
            else:
                parts.append(value)
    if not parts:
        return ""
    return f'<div class="entry"><p class="skill-tags">{" / ".join(parts)}</p></div>'


def _render_v2_item(
    item: dict, *, education: bool = False, mark: str, content: dict | None = None
) -> str:
    headline = format_entry_headline(item, education=education)
    head = f'<p class="entry-head">{_text(headline)}</p>' if headline else ""
    bullets_html = []
    for bullet in item.get("bullets") or []:
        if not isinstance(bullet, dict):
            continue
        raw = str(bullet.get("text") or "").strip()
        if not raw:
            continue
        value = _text(raw)
        if should_mark_unachieved(content, bullet):
            value = f'{value}<span class="target-label">{_text(mark)}</span>'
            bullets_html.append(f'<li class="unachieved">{value}</li>')
        else:
            bullets_html.append(f"<li>{value}</li>")
    if not head and not bullets_html:
        return ""
    if not bullets_html:
        return f'<div class="entry">{head}</div>'
    return f'<div class="entry">{head}<ul>{"".join(bullets_html)}</ul></div>'
