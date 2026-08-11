import re
from datetime import UTC, date, datetime

WEIGHTS = {
    "hard_requirements": 30,
    "skills": 25,
    "experience": 20,
    "keywords": 10,
    "preferences": 10,
    "freshness": 5,
}

ASCII_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?")
NON_ALNUM = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
REQUIREMENT_FILLER = ("要求", "必须", "熟悉", "掌握", "具备", "能够", "相关", "优先", "接受", "以上")


def score_match(facts: list, job, profile=None) -> dict:
    confirmed = [fact for fact in facts if fact.verification_status == "user_confirmed"]
    fact_text = " ".join(_fact_corpus(fact) for fact in confirmed).lower()
    must_have = [str(item).strip() for item in (job.must_have_json or []) if str(item).strip()]
    met_requirements = [item for item in must_have if requirement_matches(item, fact_text)]
    hard_ratio = len(met_requirements) / len(must_have) if must_have else 1.0
    hard = round(WEIGHTS["hard_requirements"] * hard_ratio)

    keywords = [str(item).strip() for item in (job.keywords_json or []) if str(item).strip()]
    hits = [keyword for keyword in keywords if keyword.casefold() in fact_text.casefold()]
    skills = round(WEIGHTS["skills"] * len(hits) / max(len(keywords), 1))
    experience_months = calculate_experience_months(confirmed)
    experience = round(WEIGHTS["experience"] * min(experience_months, 24) / 24)
    keyword_score = round(WEIGHTS["keywords"] * len(hits) / max(len(keywords), 1))

    confirmations = []
    preference = WEIGHTS["preferences"]
    hard_block = bool(must_have and hard_ratio < 0.5)
    work_text = " ".join(job.work_conditions_json or [])
    if "轮班" in work_text:
        if profile and profile.accepts_shift is False:
            preference = 0
            hard_block = True
        elif not profile or profile.accepts_shift is None:
            preference = 5
            confirmations.append("是否接受轮班")
    if job.status == "closed":
        freshness = 0
        hard_block = True
    elif not job.published_at:
        freshness = 2
    else:
        published = job.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - published).days
        freshness = 5 if age <= 7 else 3 if age <= 30 else 1
    dimensions = {
        "hard_requirements": hard,
        "skills": skills,
        "experience": experience,
        "keywords": keyword_score,
        "preferences": preference,
        "freshness": freshness,
    }
    total = sum(dimensions.values())
    if total >= 80 and not hard_block:
        recommendation = "优先投递"
    elif total >= 65 and not hard_block:
        recommendation = "可以尝试"
    elif total >= 50 or hard_block:
        recommendation = "低优先"
    else:
        recommendation = "不建议"

    evidence = []
    for requirement in met_requirements:
        evidence.append(
            {
                "requirement": requirement,
                "status": "met",
                "fact_ids": [
                    fact.id
                    for fact in confirmed
                    if requirement_matches(requirement, _fact_corpus(fact))
                ][:3],
                "explanation": f"已确认事实库中找到“{requirement}”相关证据。",
            }
        )
    for keyword in hits:
        if any(item["requirement"] == keyword for item in evidence):
            continue
        evidence.append(
            {
                "requirement": keyword,
                "status": "met",
                "fact_ids": [
                    fact.id
                    for fact in confirmed
                    if keyword.casefold() in _fact_corpus(fact).casefold()
                ][:3],
                "explanation": f"已确认事实库中找到“{keyword}”相关证据。",
            }
        )

    unmet_must = [item for item in must_have if item not in met_requirements]
    unmet_keywords = [
        item
        for item in keywords
        if item not in hits
        and not any(item.casefold() in requirement.casefold() for requirement in unmet_must)
    ]
    gaps = [
        {
            "requirement": requirement,
            "severity": "high",
            "category": "hard_requirements",
            "action": f"完成并验证与“{requirement}”直接相关的学习产出物。",
        }
        for requirement in unmet_must
    ]
    gaps.extend(
        {
            "requirement": requirement,
            "severity": "medium",
            "category": "skills",
            "action": f"完成并验证与“{requirement}”直接相关的学习产出物。",
        }
        for requirement in unmet_keywords
    )
    return {
        "total_score": total,
        "recommendation": recommendation,
        "dimension_scores": dimensions,
        "evidence": evidence,
        "gaps": gaps,
        "confirmations": confirmations,
        "hard_block": hard_block,
        "must_have_hit_rate": hard_ratio,
        "experience_months": experience_months,
    }


def requirement_matches(requirement: str, corpus: str) -> bool:
    required = NON_ALNUM.sub("", requirement.casefold())
    available = NON_ALNUM.sub("", corpus.casefold())
    if not required or not available:
        return False
    if required in available:
        return True
    numbers = NUMBER_TOKEN.findall(required)
    if numbers and not all(number in available for number in numbers):
        return False
    ascii_tokens = ASCII_TOKEN.findall(requirement)
    if ascii_tokens and not all(token.casefold() in corpus.casefold() for token in ascii_tokens):
        return False
    chinese = "".join(character for character in required if "\u4e00" <= character <= "\u9fff")
    for filler in REQUIREMENT_FILLER:
        chinese = chinese.replace(filler, "")
    if len(chinese) < 2:
        return bool(ascii_tokens or numbers)
    bigrams = {chinese[index : index + 2] for index in range(len(chinese) - 1)}
    if not bigrams:
        return False
    hit_ratio = sum(token in available for token in bigrams) / len(bigrams)
    return hit_ratio >= 0.35


def calculate_experience_months(facts: list, *, today: date | None = None) -> int:
    current = today or datetime.now(UTC).date()
    intervals = []
    for fact in facts:
        if getattr(fact, "category", "") not in {"employment", "projects"}:
            continue
        start = _month_index(getattr(fact, "start_date", ""))
        end_value = getattr(fact, "end_date", "")
        end = current.year * 12 + current.month if end_value == "至今" else _month_index(end_value)
        if start is None or end is None or end < start:
            continue
        intervals.append((start, end + 1))
    if not intervals:
        return 0
    intervals.sort()
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def _month_index(value: str) -> int | None:
    match = re.fullmatch(r"((?:19|20)\d{2})-(0[1-9]|1[0-2])(?:-[0-3]\d)?", value or "")
    return int(match.group(1)) * 12 + int(match.group(2)) if match else None


def _fact_corpus(fact) -> str:
    values = [
        str(getattr(fact, "value_json", {}).get("text", "")),
        str(getattr(fact, "organization", "")),
        str(getattr(fact, "role_title", "")),
        str(getattr(fact, "source_text", "")),
    ]
    return " ".join(value for value in values if value)
