import io
import re

import pdfplumber
from docx import Document

from app.errors import AppError


ALLOWED = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/pdf": ".pdf",
}

_METRIC_PATTERN = re.compile(r"\d+(?:\.\d+)?(?:%|％|万|千|百|倍|人|月|年|天|个|项|次|台|套)")
_WEAK_VERBS = re.compile(r"^(?:负责|参与|协助|帮忙|帮忙|帮助)")
_STRONG_VERBS = re.compile(
    r"^(?:主导|统筹|牵头|搭建|开发|实现|完成|落地|优化|重构|改进|升级|迭代|"
    r"协调|推动|对接|联动|协同|达成|突破|创造|实现|"
    r"分析|诊断|评估|调研|洞察|策划|设计|构思|提出|创新|"
    r"管理|运营|维护|监控|保障|带领|规划)"
)

_CATEGORY_PATTERNS = [
    ("personal_info", re.compile(r"(?:手机|电话|邮箱|email|地址|出生|年龄|性别|籍贯|政治面貌|求职意向|期望)", re.I)),
    ("summary", re.compile(r"(?:自我评价|个人总结|个人简介|技能特长|核心优势|专业背景)")),
    ("education", re.compile(r"(?:大学|学院|本科|硕士|博士|专科|高中|GPA|绩点|专业|学位|学历|985|211|双一流|重点)")),
    ("certificates", re.compile(r"(?:证书|资格|执照|PMP|CPA|CFA|CFA|雅思|托福|N1|N2|六级|四级|软考)")),
    ("awards", re.compile(r"(?:获奖|荣誉|奖学金|优秀|竞赛|比赛|一等奖|二等奖|三等奖)")),
    ("skills", re.compile(
        r"(?:CAD|SolidWorks|Python|Java|JavaScript|React|Vue|SQL|SOP|Excel|"
        r"Photoshop|Figma|Sketch|Tableau|Power\s*BI|SPSS|R语言|"
        r"Spring|Django|Flask|FastAPI|MySQL|PostgreSQL|MongoDB|Redis|"
        r"Docker|Kubernetes|AWS|Azure|Git|Linux|"
        r"Office|Word|PPT|PowerPoint)",
        re.I,
    )),
    ("projects", re.compile(r"(?:项目|课题|系统|平台|模块|功能|版本|上线|发布)")),
    ("employment", re.compile(r"(?:实习|工作|公司|集团|研究院|研究所|在职|离职|任职|岗位|职位)")),
]

_SECTION_HEADERS = re.compile(
    r"^(?:教育|工作|实习|项目|技能|证书|荣誉|获奖|自我评价|个人[总简]|"
    r"求职意向|核心优势|专业背景|基本信息|联系方式|"
    r"(?:工作|实习|项目|技能|证书|教育)(?:经[历验])?)$"
)


def parse_resume(content: bytes, media_type: str, filename: str) -> tuple[str, list[dict]]:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Use filename extension as primary check, media_type as secondary
    if suffix == ".docx":
        expected_media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif suffix == ".pdf":
        expected_media = "application/pdf"
    else:
        raise AppError("UNSUPPORTED_RESUME_TYPE", "仅支持 DOCX 或文本型 PDF 文件。", 415)

    # Allow if media_type matches OR if media_type is generic (octet-stream) but extension is valid
    if media_type and media_type != "application/octet-stream" and media_type != expected_media:
        raise AppError("UNSUPPORTED_RESUME_TYPE", "仅支持 DOCX 或文本型 PDF 文件。", 415)
    try:
        if suffix == ".docx":
            doc = Document(io.BytesIO(content))
            parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        parts.append(" | ".join(dict.fromkeys(cells)))
            text = "\n".join(parts)
        else:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
            if not text:
                raise AppError(
                    "SCANNED_PDF_UNSUPPORTED", "该 PDF 可能是扫描件，MVP 暂不支持 OCR。", 422
                )
    except AppError:
        raise
    except Exception as exc:
        raise AppError("RESUME_PARSE_FAILED", "文件无法解析，请确认文件未损坏。", 422) from exc
    if not text.strip():
        raise AppError("EMPTY_RESUME", "简历中没有可解析的文本。", 422)
    facts = extract_facts(text)
    return text, facts


def _classify_line(line: str) -> str:
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(line):
            return category
    return "other"


def _detect_verb_type(line: str) -> str:
    if _STRONG_VERBS.match(line):
        return "strong"
    if _WEAK_VERBS.match(line):
        return "weak"
    return "none"


def extract_facts(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 2]
    facts = []
    for line in lines[:200]:
        if _SECTION_HEADERS.match(line):
            continue
        category = _classify_line(line)
        has_metrics = bool(_METRIC_PATTERN.search(line))
        verb_type = _detect_verb_type(line)
        facts.append(
            {
                "category": category,
                "label": line[:30],
                "value_json": {
                    "text": line,
                    "has_metrics": has_metrics,
                    "verb_type": verb_type,
                },
                "source_text": line,
            }
        )
    return facts[:50]
