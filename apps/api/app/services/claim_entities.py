import re

NUMBER_ENTITY = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|倍|万|k|K|人|天|月|年|个)?")
ENGLISH_TECH_ENTITY = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
CERTIFICATE_ENTITY = re.compile(r"证书|资格证|等级考试|职业资格|CET|PMP|CFA|六西格玛|绿带|黑带", re.IGNORECASE)
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
