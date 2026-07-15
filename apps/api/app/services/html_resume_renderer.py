from html import escape


def _text(value) -> str:
    return escape(str(value or ""), quote=True)


def render_resume_html(content: dict, title: str) -> str:
    """Render an approved resume version as a self-contained, escaped A4 document."""
    headline = _text(content.get("headline") or title)
    sections_html: list[str] = []
    sections = content.get("sections", [])
    if not isinstance(sections, list):
        sections = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        name = _text(section.get("name") or "相关经历")
        items_html: list[str] = []
        items = section.get("items", [])
        if not isinstance(items, list):
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            value = _text(item.get("text"))
            if value:
                items_html.append(f"<li>{value}</li>")
        if items_html:
            sections_html.append(
                f"<section><h2>{name}</h2><ul>{''.join(items_html)}</ul></section>"
            )
    body = "".join(sections_html) or '<p class="empty">暂无可导出的已审核内容。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{headline}</title>
<style>
*{{box-sizing:border-box}}html,body{{margin:0;padding:0}}body{{background:#ecebe6;color:#20231f;font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-size:13px;line-height:1.55}}.page{{width:210mm;min-height:297mm;margin:18px auto;background:#fff;padding:16mm 18mm 14mm;box-shadow:0 2px 16px #0002;transform-origin:top left}}header{{border-bottom:2px solid #31483a;padding-bottom:10px;margin-bottom:14px}}h1{{font-size:24px;line-height:1.25;margin:0;color:#1c2d23}}section{{margin:0 0 12px;break-inside:avoid}}h2{{font-size:15px;margin:0 0 6px;border-bottom:1px solid #ccd3cd;padding-bottom:3px;color:#31483a}}ul{{margin:0;padding:0;list-style:none}}li{{position:relative;padding-left:13px;margin:0 0 4px}}li::before{{content:"•";position:absolute;left:1px;color:#55735f}}.empty{{color:#777}}@page{{size:A4;margin:0}}@media print{{body{{background:#fff}}.page{{margin:0;box-shadow:none}}}}
</style>
</head>
<body>
<main class="page" id="resume-page"><header><h1>{headline}</h1></header>{body}</main>
<script>(function(){{var p=document.getElementById("resume-page"),limit=1122;if(p&&p.scrollHeight>limit){{var s=Math.max(.78,limit/p.scrollHeight);p.style.transform="scale("+s.toFixed(3)+")";p.style.width=(210/s).toFixed(2)+"mm"}}}})();</script>
</body>
</html>"""
