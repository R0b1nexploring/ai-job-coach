import hashlib
import re
import unicodedata

KEYWORDS = [
    "设备点检",
    "SOP",
    "CAD",
    "SolidWorks",
    "机械",
    "本科",
    "轮班",
    "出差",
    "维护",
    "跨部门",
]

_TITLE_PATTERN = re.compile(
    r"(?:[\u4e00-\u9fffA-Za-z0-9·+/#（）()\- ]{0,24})"
    r"(?:工程师|实习生|专员|经理|主管|总监|顾问|研究员|设计师|分析师|开发者|运营)"
)
_IDENTITY_LABEL_PATTERN = re.compile(r"^(?:岗位(?:名称|职位)?|职位(?:名称)?|招聘岗位)\s*[:：]\s*(.+)$")
_COMPANY_LABEL_PATTERN = re.compile(r"^(?:公司(?:名称)?|企业(?:名称)?|招聘单位|用人单位)\s*[:：]\s*(.+)$")


def _infer_title(lines: list[str]) -> str:
    for line in lines[:8]:
        labelled = _IDENTITY_LABEL_PATTERN.match(line)
        candidate = labelled.group(1).strip() if labelled else line
        if re.search(r"岗位职责|职位描述|任职要求|职责要求", candidate):
            continue
        match = _TITLE_PATTERN.search(candidate)
        if match:
            return match.group(0).strip(" -•：:")[:200]
    return ""


def _infer_company(lines: list[str]) -> str:
    for line in lines[:8]:
        labelled = _COMPANY_LABEL_PATTERN.match(line)
        if labelled:
            return labelled.group(1).strip()[:200]
    return ""


def normalize_job(raw_jd: str, title: str = "", company_name: str = "", city: str = "") -> dict:
    lines = [x.strip(" -•\t") for x in raw_jd.splitlines() if x.strip()]
    inferred_title = title.strip() or _infer_title(lines)
    inferred_company = company_name.strip() or _infer_company(lines)
    must = [x for x in lines if re.search(r"要求|本科|专业|必须|熟悉|接受", x)][:8]
    responsibilities = [x for x in lines if re.search(r"负责|协助|维护|编制|跟进", x)][:8]
    nice = [x for x in lines if re.search(r"优先|加分", x)][:5]
    keywords = [k for k in KEYWORDS if k.lower() in raw_jd.lower()]
    work = [x for x in lines if re.search(r"轮班|出差|工厂", x)][:5]
    return {
        "title": inferred_title,
        "company_name": inferred_company,
        "city": city,
        "responsibilities": responsibilities,
        "must_have": must,
        "nice_to_have": nice,
        "keywords": keywords,
        "work_conditions": work,
        "uncertain_fields": [
            k
            for k, v in {
                "title": inferred_title,
                "company_name": inferred_company,
                "city": city,
            }.items()
            if not v
        ],
        "content_hash": hashlib.sha256(raw_jd.strip().encode()).hexdigest(),
    }


def ground_job_output(
    candidate: dict,
    *,
    raw_jd: str,
    title: str = "",
    company_name: str = "",
    city: str = "",
    fallback: dict | None = None,
) -> dict:
    """Project untrusted LLM output onto user input and verbatim JD evidence.

    Explicit user fields are authoritative. Every AI-proposed field or list
    item must otherwise be present in the raw JD; invalid proposals are
    replaced with deterministic, source-grounded values.
    """

    fallback = fallback or normalize_job(raw_jd, title, company_name, city)
    source = _grounding_text(raw_jd)

    def is_grounded(value) -> bool:
        normalized = _grounding_text(str(value or ""))
        return bool(normalized and normalized in source)

    result = {}
    for field, explicit in (
        ("title", title),
        ("company_name", company_name),
        ("city", city),
    ):
        explicit_value = str(explicit or "").strip()
        proposed = str(candidate.get(field) or "").strip()
        result[field] = (
            explicit_value
            if explicit_value
            else proposed
            if is_grounded(proposed)
            else str(fallback.get(field) or "").strip()
        )

    for field in (
        "responsibilities",
        "must_have",
        "nice_to_have",
        "keywords",
        "work_conditions",
    ):
        proposed = candidate.get(field) if isinstance(candidate.get(field), list) else []
        grounded = [str(value).strip() for value in proposed if is_grounded(value)]
        if not grounded:
            grounded = [
                str(value).strip()
                for value in fallback.get(field) or []
                if is_grounded(value)
            ]
        result[field] = list(dict.fromkeys(value for value in grounded if value))

    allowed_uncertain = {"title", "company_name", "city", "published_at"}
    result["uncertain_fields"] = list(
        dict.fromkeys(
            str(value)
            for value in candidate.get("uncertain_fields") or []
            if str(value) in allowed_uncertain
        )
    )
    for field, explicit in (("title", title), ("company_name", company_name), ("city", city)):
        if not str(explicit or "").strip() and not result[field] and field not in result["uncertain_fields"]:
            result["uncertain_fields"].append(field)
    result["content_hash"] = fallback["content_hash"]
    return result


def _grounding_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"\s+", "", normalized)
