from app.services.html_resume_renderer import render_resume_html


def test_html_renderer_escapes_resume_content_and_is_print_ready():
    content = {
        "headline": "设备工程师 <script>alert(1)</script>",
        "sections": [{"name": "项目经历", "items": [{"text": "完成 CAD 设计 <img src=x onerror=alert(1)>"}]}],
    }
    result = render_resume_html(content, "备用标题")
    assert "<script>alert(1)</script>" not in result
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
    assert "&lt;img src=x onerror=alert(1)&gt;" in result
    assert "@page" in result and "size:A4" in result
