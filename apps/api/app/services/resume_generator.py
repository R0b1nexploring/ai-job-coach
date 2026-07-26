from .fact_guard import guard_content

_SECTION_ORDER = {
    "employment": 0,
    "projects": 1,
    "skills": 2,
    "certificates": 3,
    "education": 4,
    "awards": 5,
    "summary": 6,
    "personal_info": 7,
    "other": 8,
}

_ATS_NAMES = {
    "employment": "工作经历",
    "projects": "项目经验",
    "skills": "技能证书",
    "certificates": "技能证书",
    "education": "教育背景",
    "awards": "荣誉奖项",
    "summary": "自我评价",
    "personal_info": "基本信息",
    "other": "其他经历",
}

_STRONG_VERB_HINTS = {
    "employment": "用「主导/统筹/搭建/推动」替代「负责/参与」，补充行动方法与量化结果",
    "projects": "用 STAR 法则展开：背景→任务→行动→量化结果",
    "skills": "标注熟练度（精通/熟练/掌握/了解），与 JD 关键词对齐",
}


def _improvement_for(fact, requirements: list[str]) -> list[str]:
    suggestions = []
    value = fact.value_json if isinstance(fact.value_json, dict) else {}
    text = str(value.get("text", fact.label))
    has_metrics = value.get("has_metrics", False)
    verb_type = value.get("verb_type", "none")

    if not has_metrics and fact.category in ("employment", "projects"):
        suggestions.append("建议补充量化数据（如提升比例、处理数量、覆盖范围）")
    if verb_type == "weak":
        suggestions.append(_STRONG_VERB_HINTS.get(fact.category, "建议使用更有力的动词"))

    text_lower = text.lower()
    missed = [r for r in requirements if r.lower() not in text_lower]
    if missed and fact.category in ("employment", "projects", "skills"):
        suggestions.append(f"可补充与岗位相关的能力：{'、'.join(missed[:3])}")
    return suggestions


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
        text = str(fact.value_json.get("text", fact.label) if isinstance(fact.value_json, dict) else fact.label).lower()
        return sum(1 for requirement in requirements if requirement.lower() in text)

    ordered = sorted(
        source_facts,
        key=lambda fact: (-relevance(fact), _SECTION_ORDER.get(fact.category, 9)),
    )

    grouped = {}
    for fact in ordered[:20]:
        text = str(fact.value_json.get("text", fact.label) if isinstance(fact.value_json, dict) else fact.label)
        hits = [r for r in requirements if r.lower() in text.lower()]
        suggestions = _improvement_for(fact, requirements)
        grouped.setdefault(fact.category, []).append(
            {
                "text": text,
                "source_fact_ids": [fact.id],
                "target_requirement_ids": hits,
                "new_claims": [],
                "improvement_suggestions": suggestions,
            }
        )

    sections = []
    for category in sorted(grouped, key=lambda c: _SECTION_ORDER.get(c, 9)):
        sections.append({
            "name": _ATS_NAMES.get(category, "其他经历"),
            "items": grouped[category],
        })

    if inject_unverified:
        if not sections:
            sections.append({"name": "工作经历", "items": []})
        sections[0]["items"].append(
            {
                "text": "优化流程并提升效率 30%",
                "source_fact_ids": [source_facts[0].id] if source_facts else [],
                "target_requirement_ids": [],
                "new_claims": [],
                "improvement_suggestions": [],
            }
        )

    all_source_text = " ".join(
        str(f.value_json.get("text", "") if isinstance(f.value_json, dict) else "")
        for f in source_facts
    ).lower()
    excluded_gaps = []
    for keyword in (job.keywords_json or []):
        if keyword.lower() not in all_source_text:
            excluded_gaps.append(keyword)

    content = {
        "headline": f"{job.title}方向求职简历",
        "sections": sections,
        "excluded_gaps": excluded_gaps,
    }
    status, new_claims = guard_content(content, source_facts)
    return content, status, new_claims
