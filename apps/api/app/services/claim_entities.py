import re

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


def unsupported_chinese_claims(text: str, corpus: str) -> list[str]:
    """Return compact diagnostics for materially unsupported Chinese prose.

    Entity extraction catches numbers, tools and certificates, but a sentence
    such as ``主导供应链优化`` contains none of those entities.  We therefore
    also require Chinese bigram overlap with the sources cited by the same
    bullet.  This is intentionally conservative: an unsupported model rewrite
    falls back to deterministic source text instead of being accepted as fact.
    """

    raw_claim = _normalized_chinese_claim(text, strip_prefix=False)
    claim = _normalized_chinese_claim(text)
    allowed = _normalized_chinese_claim(corpus, strip_prefix=False)
    if not claim:
        return []
    # Inspect the unstripped claim.  Some terms (for example ``掌握``) are
    # allowed as deterministic presentation prefixes, but they are still a
    # material assertion and must already appear in the cited source.
    issues = [
        term for term in CHINESE_HIGH_RISK_TERMS if term in raw_claim and term not in allowed
    ]
    claim_bigrams = _chinese_bigrams(claim)
    if not claim_bigrams:
        # A one-character claim is too weak to verify semantically; the other
        # entity guards still apply.
        return sorted(issues)
    allowed_bigrams = _chinese_bigrams(allowed)
    unsupported = sorted(claim_bigrams - allowed_bigrams - CHINESE_STOP_BIGRAMS)
    # A short fabricated suffix keeps most bigrams from the source, so a ratio
    # threshold lets claims such as “参与设计并交付” or “实现商业化” pass.  A
    # neutral leading verb remains supported because the stripped claim is a
    # literal substring of the cited corpus; any other new Chinese bigram is a
    # material rewrite and must fall back to source-grounded text.
    if unsupported and claim not in allowed:
        issues.append("中文主张与引用来源语义不一致")
    return list(dict.fromkeys(sorted(issues)))


def _normalized_chinese_claim(value: str, *, strip_prefix: bool = True) -> str:
    text = "".join(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value or ""))
    if strip_prefix:
        prefix = next((item for item in NEUTRAL_LEADING_PREFIXES if text.startswith(item)), "")
        if prefix:
            text = text[len(prefix) :]
    return text


def _chinese_bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(max(0, len(value) - 1))}
