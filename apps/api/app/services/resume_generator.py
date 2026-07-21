from .fact_guard import guard_content


def generate_resume(
    facts: list,
    job,
    inject_unverified: bool = False,
    allowed_statuses: set[str] | None = None,
):
    """Build a traceable draft from explicitly allowed source-fact statuses."""
    statuses = allowed_statuses or {"user_confirmed"}
    source_facts = [f for f in facts if f.verification_status in statuses]
    requirements = list(dict.fromkeys([*(job.must_have_json or []), *(job.keywords_json or [])]))

    def relevance(fact):
        text = str(fact.value_json.get("text", fact.label)).lower()
        return sum(1 for requirement in requirements if requirement.lower() in text)

    category_order = {
        "employment": 0,
        "projects": 1,
        "skills": 2,
        "education": 3,
        "certificates": 4,
        "other": 5,
    }
    ordered = sorted(
        source_facts,
        key=lambda fact: (-relevance(fact), category_order.get(fact.category, 9)),
    )
    grouped = {}
    names = {
        "employment": "工作与实习经历",
        "projects": "项目经历",
        "skills": "技能",
        "education": "教育背景",
        "certificates": "证书",
        "other": "其他经历",
    }
    for fact in ordered[:12]:
        text = str(fact.value_json.get("text", fact.label))
        hits = [requirement for requirement in requirements if requirement.lower() in text.lower()]
        grouped.setdefault(fact.category, []).append(
            {
                "text": text,
                "source_fact_ids": [fact.id],
                "target_requirement_ids": hits,
                "new_claims": [],
            }
        )
    sections = [
        {"name": names.get(category, "其他经历"), "items": items}
        for category, items in grouped.items()
    ]
    if inject_unverified:
        if not sections:
            sections.append({"name": "相关经历", "items": []})
        sections[0]["items"].append(
            {
                "text": "优化流程并提升效率 30%",
                "source_fact_ids": [source_facts[0].id] if source_facts else [],
                "target_requirement_ids": [],
                "new_claims": [],
            }
        )
    content = {
        "headline": f"{job.title}方向求职简历",
        "sections": sections,
        "excluded_gaps": [
            k
            for k in (job.keywords_json or [])
            if not any(k.lower() in str(f.value_json).lower() for f in source_facts)
        ],
    }
    status, new_claims = guard_content(content, source_facts)
    return content, status, new_claims
