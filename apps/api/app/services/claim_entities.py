import re

from collections.abc import Sequence

NUMBER_ENTITY = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|倍|万|k|K|人|天|月|年|个)?")
ENGLISH_TECH_ENTITY = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
CERTIFICATE_ENTITY = re.compile(
    r"证书|资格证|等级考试|职业资格|CET|PMP|CFA|六西格玛|绿带|黑带",
    re.IGNORECASE,
)
ENGLISH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}

# These words change the meaning or ownership of a Chinese resume claim.  They
# are deliberately not treated as harmless writing style: if a bullet says the
# user led, independently completed, optimised or mastered something, that
# wording must exist in one of that bullet's cited sources.
CHINESE_HIGH_RISK_TERMS = {
    "主导",
    "独立",
    "领导",
    "管理",
    "负责",
    "优化",
    "提升",
    "降低",
    "节省",
    "精通",
    "熟练",
    "获得",
    "通过",
    "带领",
    "统筹",
    # Delivery, recognition and ownership claims are easy for a model to add
    # as a short suffix while retaining most of the source wording.  Bigram
    # overlap alone cannot safely detect that pattern.
    "量产",
    "投产",
    "上线",
    "落地",
    "获奖",
    "专利",
    "认证",
    "掌握",
}

# Deterministic rendering may add one neutral action prefix to source text.
# Removing only a leading prefix keeps that formatting compatible while the
# remaining Chinese claim still has to overlap with its cited source.
NEUTRAL_LEADING_PREFIXES = (
    "完成",
    "使用",
    "参与",
    "协助",
    "设计",
    "开发",
    "维护",
    "编制",
    "搭建",
    "分析",
    "验证",
    "实现",
    "制作",
    "推进",
    "支持",
    "学习",
    "掌握",
    "输出",
    "具备",
    "积累",
    "围绕",
)
CHINESE_STOP_BIGRAMS = {
    "以及",
    "相关",
    "进行",
    "通过",
    "并且",
    "其中",
    "工作",
    "项目",
    "能力",
}


def extract_claim_entities(text: str) -> list[str]:
    values = list(NUMBER_ENTITY.findall(text or ""))
    values.extend(
        token
        for token in ENGLISH_TECH_ENTITY.findall(text or "")
        if token.casefold() not in ENGLISH_STOP_WORDS
    )
    values.extend(CERTIFICATE_ENTITY.findall(text or ""))
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def corpus_contains(corpus: str, entity: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value).replace("％", "%").casefold()

    return normalize(entity) in normalize(corpus)


def unsupported_chinese_claims(text: str, corpus: str | Sequence[str]) -> list[str]:
    """Return compact diagnostics for materially unsupported Chinese prose.

    Entity extraction catches numbers, tools and certificates, but a sentence
    such as ``主导供应链优化`` contains none of those entities. This check adds
    two conservative signals on top of that:

    1. a high-risk ownership/delivery term that no cited source contains; and
    2. a source phrase reproduced verbatim with extra material wording attached
       ("参与机械机构设计" -> "参与机械机构设计交付").

    It deliberately does NOT flag ordinary editorial rewrites. An earlier
    version required nearly every Chinese bigram to appear in the sources, which
    rejected reworded copies such as "输出装配体与二维工程图" ->
    "输出小型减速箱二维工程图，与三维装配体配套" and silently downgraded the
    candidate's own confirmed experience to ``ai_generated``.

    ``corpus`` may be a pre-joined string or the individual source fields. Pass
    the fields when available: a joined string cannot be split reliably because
    a single field may itself contain spaces, and a mid-sentence split creates
    fragments that match a claim by accident.
    """

    raw_claim = _normalized_chinese_claim(text, strip_prefix=False)
    claim = _normalized_chinese_claim(text)
    sources = _source_fields(corpus)
    allowed = _normalized_chinese_claim(" ".join(sources), strip_prefix=False)
    if not claim:
        return []
    # Inspect the unstripped claim. Some terms (for example ``掌握``) are
    # allowed as deterministic presentation prefixes, but they are still a
    # material assertion and must already appear in the cited source.
    issues = [
        term for term in CHINESE_HIGH_RISK_TERMS if term in raw_claim and term not in allowed
    ]
    if _appends_to_a_source_phrase(raw_claim, sources) or _is_unrelated_to_sources(claim, allowed):
        issues.append("中文主张与引用来源语义不一致")
    return list(dict.fromkeys(sorted(issues)))


# Measured on real model output, legitimate rewrites keep at least ~0.38 of
# their bigrams. This floor sits below that with margin, so only text written
# from scratch (essentially no shared vocabulary) is treated as unrelated.
_MIN_SOURCE_OVERLAP = 0.25


def _is_unrelated_to_sources(claim: str, allowed: str) -> bool:
    """Whether a claim shares almost no wording with its cited sources."""
    claim_bigrams = _chinese_bigrams(claim)
    if not claim_bigrams:
        return False
    allowed_bigrams = _chinese_bigrams(allowed)
    overlap = len(claim_bigrams & allowed_bigrams) / len(claim_bigrams)
    return overlap < _MIN_SOURCE_OVERLAP


def _source_fields(corpus: str | Sequence[str]) -> list[str]:
    """Normalize the cited sources into individual fields.

    A bare string is split on whitespace to preserve the historical call
    convention; callers that already hold the fields should pass them directly.
    """
    if isinstance(corpus, str):
        return [value for value in corpus.split() if value.strip()]
    return [str(value) for value in corpus if str(value).strip()]


def _appends_to_a_source_phrase(raw_claim: str, sources: Sequence[str]) -> bool:
    """Whether the claim quotes one source field and adds material wording.

    Extra wording that only restates another cited field, or that is a neutral
    presentation prefix/suffix or a rendering label, is not an added claim.
    """
    normalized = sorted(
        {
            value
            for item in sources
            if (value := _normalized_chinese_claim(item, strip_prefix=False))
        },
        key=len,
        reverse=True,
    )
    pool = "".join(normalized)
    for source in normalized:
        if source not in raw_claim or len(raw_claim) <= len(source):
            continue
        leftover = raw_claim.replace(source, "", 1)
        for prefix in NEUTRAL_LEADING_PREFIXES:
            if leftover.startswith(prefix):
                leftover = leftover[len(prefix) :]
            if leftover.endswith(prefix):
                leftover = leftover[: -len(prefix)]
        for marker in _PRESENTATION_MARKERS:
            leftover = leftover.replace(marker, "")
        if not leftover:
            continue
        # The remainder may simply be another cited field, which is normal when
        # a fact's text, organization and dates are separate sources.
        if leftover in pool:
            continue
        return True
    return False


# Labels the local assembler and writer add when presenting a bullet. They
# carry no claim of their own.
_PRESENTATION_MARKERS = ("证据", "来源", "目标", "计划", "待补充", "说明", "备注", "依据")


def _normalized_chinese_claim(value: str, *, strip_prefix: bool = True) -> str:
    text = "".join(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value or ""))
    if strip_prefix:
        prefix = next((item for item in NEUTRAL_LEADING_PREFIXES if text.startswith(item)), "")
        if prefix:
            text = text[len(prefix) :]
    return text


def _chinese_bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(max(0, len(value) - 1))}
