import io
import zipfile
from xml.etree import ElementTree

from docx import Document

from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def v2_content():
    return {
        "content_version": 2,
        "kind": "target",
        "headline": "机械设计工程师",
        "contact": {
            "name": "张三",
            "phone": "13800000000",
            "email": "zhangsan@example.test",
            "city": "杭州",
        },
        "sections": [
            {
                "name": "项目经历",
                "items": [
                    {
                        "organization": "示例大学",
                        "role_title": "项目负责人",
                        "location": "杭州",
                        "start_date": "2024-03",
                        "end_date": "2024-06",
                        "bullets": [
                            {
                                "text": "完成 CAD 机构设计",
                                "source_fact_ids": ["fact-1"],
                                "source_target_ids": [],
                                "achieved": True,
                            },
                            {
                                "text": "围绕 SolidWorks 完成装配体练习",
                                "source_fact_ids": [],
                                "source_target_ids": ["target-1"],
                                "achieved": False,
                            },
                        ],
                    }
                ],
            },
            {
                "name": "教育背景",
                "items": [
                    {
                        "organization": "示例大学",
                        "role_title": "机械工程本科",
                        "start_date": "2021-09",
                        "end_date": "2025-06",
                        "bullets": [
                            {
                                "text": "具备机械工程本科背景",
                                "source_fact_ids": ["fact-2"],
                                "source_target_ids": [],
                                "achieved": True,
                            }
                        ],
                    }
                ],
            },
        ],
        "excluded_gaps": [],
    }


def test_html_renderer_escapes_v1_resume_content_and_is_print_ready():
    content = {
        "headline": "设备工程师 <script>alert(1)</script>",
        "sections": [
            {"name": "项目经历", "items": [{"text": "完成 CAD 设计 <img src=x onerror=alert(1)>"}]}
        ],
    }
    result = render_resume_html(content, "备用标题")
    assert "<script>alert(1)</script>" not in result
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
    assert "&lt;img src=x onerror=alert(1)&gt;" in result
    assert "@page" in result and "size:A4" in result
    assert "scale(" not in result


def test_docx_uses_a4_and_portable_chinese_fonts():
    content = render_resume_docx(v2_content(), "备用标题")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml")
        styles_xml = archive.read("word/styles.xml")
    root = ElementTree.fromstring(document_xml)
    page_size = root.find(f".//{{{WORD_NS}}}pgSz")
    assert page_size is not None
    assert page_size.attrib[f"{{{WORD_NS}}}w"] == "11906"
    assert page_size.attrib[f"{{{WORD_NS}}}h"] == "16838"
    styles_text = styles_xml.decode("utf-8")
    assert "微软雅黑" in styles_text
    assert "黑体" in styles_text
    assert "Calibri" in styles_text
    assert "Arial Unicode MS" not in styles_text
    assert 'w:styleId="ResumeBullet"' in styles_text
    assert 'w:basedOn w:val="ListBullet"' in styles_text
    assert b'<w:tab w:val="right"' in styles_xml


def test_v2_html_and_docx_show_same_sections_bullets_and_unachieved_marker():
    content = v2_content()
    html = render_resume_html(content, "备用标题")
    docx_bytes = render_resume_docx(content, "备用标题")
    document = Document(io.BytesIO(docx_bytes))
    section_count = sum(paragraph.style.name == "Resume Section" for paragraph in document.paragraphs)
    bullet_count = sum(paragraph.style.name == "Resume Bullet" for paragraph in document.paragraphs)
    assert html.count('data-resume-section="true"') == section_count == 2
    assert html.count("<li") == bullet_count == 3
    assert "未达成 · 学习目标" in html
    assert any("未达成 · 学习目标" in paragraph.text for paragraph in document.paragraphs)
    assert "13800000000 · zhangsan@example.test · 杭州" in html
    assert any("13800000000 · zhangsan@example.test · 杭州" in p.text for p in document.paragraphs)
