from datetime import datetime, timezone


WEIGHTS = {
    "hard_requirements": 30,
    "skills": 25,
    "experience": 20,
    "keywords": 10,
    "preferences": 10,
    "freshness": 5,
}


def score_match(facts: list, job, profile=None) -> dict:
    fact_text = " ".join(
        str(f.value_json.get("text", ""))
        for f in facts
        if f.verification_status == "user_confirmed"
    ).lower()
    keywords = job.keywords_json or []
    hits = [k for k in keywords if k.lower() in fact_text]
    education_hit = any(x in fact_text for x in ["本科", "硕士", "机械"])
    hard = 24 if education_hit else 12
    skills = round(25 * len(hits) / max(len(keywords), 1))
    experience = 16 if any(x in fact_text for x in ["项目", "设计", "实习", "维护"]) else 6
    keyword_score = round(10 * len(hits) / max(len(keywords), 1))
    confirmations = []
    preference = 10
    hard_block = False
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
            published = published.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - published).days
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
    evidence = [
        {
            "requirement": k,
            "status": "met",
            "fact_ids": [
                f.id
                for f in facts
                if f.verification_status == "user_confirmed"
                and k.lower() in str(f.value_json).lower()
            ][:3],
            "explanation": f"已确认事实库中找到“{k}”相关证据。",
        }
        for k in hits
    ]
    gaps = [
        {"requirement": k, "severity": "medium", "action": f"补充可验证的{k}练习或事实"}
        for k in keywords
        if k not in hits
    ]
    return {
        "total_score": total,
        "recommendation": recommendation,
        "dimension_scores": dimensions,
        "evidence": evidence,
        "gaps": gaps,
        "confirmations": confirmations,
        "hard_block": hard_block,
    }
