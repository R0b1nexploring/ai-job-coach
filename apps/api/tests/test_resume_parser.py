from app.services.resume_parser import deterministic_extraction, normalize_extracted_text


SPACED_RESUME = """
张 三 性 别：男 年 龄：22岁
电 话：13800000000 邮 箱：zhangsan@example.test
教育背景
示例大学｜机械工程本科｜2022.09–2026.07
实习经历
机械助理工程师｜示例精密机械有限公司｜2025.07–2025.10
公司需要优化生产线设计，提高产能和产品可制造性。
使用 SolidWorks 进行零件和装配设计。
项目经历
工作流数据库管理｜2024.12–2025.03
技能证书及奖项
英语 CET-6；SolidWorks；Python
"""


def test_normalize_collapses_spaced_cjk_name():
    assert "张三性别" in normalize_extracted_text("张 三 性 别：男")


def test_deterministic_extraction_reads_spaced_header_and_skips_duty_as_org():
    extracted = deterministic_extraction(normalize_extracted_text(SPACED_RESUME))
    assert extracted["contact"]["name"] == "张三"
    assert extracted["contact"]["email"] == "zhangsan@example.test"
    orgs = [fact["organization"] for fact in extracted["facts"]]
    assert "示例大学" in orgs
    assert "示例精密机械有限公司" in orgs
    assert not any(str(org).startswith("公司需要") for org in orgs)
    texts = " ".join(fact["text"] for fact in extracted["facts"])
    assert "CET-6" in texts or any(fact["category"] == "certificates" for fact in extracted["facts"])
    assert not extracted["missing_information"]
