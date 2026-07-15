from collections import Counter


ROLE_RULES = [
    ("设备工程师", ["机械", "设备", "点检", "维护", "cad", "sop"]),
    ("机械设计工程师", ["机械", "设计", "cad", "solidworks", "机构", "制图"]),
    ("制造工艺工程师", ["制造", "工艺", "生产", "精益", "质量", "sop"]),
    ("质量工程师", ["质量", "检验", "测试", "体系", "审核", "统计"]),
    ("项目助理", ["项目", "协调", "沟通", "计划", "文档", "交付"]),
    ("数据分析助理", ["数据", "python", "sql", "excel", "分析", "可视化"]),
    ("软件开发工程师", ["python", "java", "javascript", "react", "开发", "系统"]),
]


def analyze_resume(facts: list, profile=None) -> dict:
    available = [fact for fact in facts if fact.verification_status != "user_rejected"]
    confirmed = [fact for fact in available if fact.verification_status == "user_confirmed"]
    source = confirmed or available
    text = " ".join(str(fact.value_json.get("text", fact.label)) for fact in source).lower()
    suggestions = []
    for role, keywords in ROLE_RULES:
        hits = [keyword for keyword in keywords if keyword in text]
        if hits:
            evidence_ids = [
                fact.id
                for fact in source
                if any(hit in str(fact.value_json.get("text", fact.label)).lower() for hit in hits)
            ]
            suggestions.append(
                {
                    "role": role,
                    "reason": f"简历中出现与该方向相关的内容：{'、'.join(hits[:4])}。",
                    "evidence_fact_ids": evidence_ids[:5],
                    "search_keywords": list(dict.fromkeys([role, *hits]))[:6],
                }
            )
    profile_roles = list(getattr(profile, "target_roles_json", []) or [])
    for role in profile_roles:
        if role and all(item["role"] != role for item in suggestions):
            suggestions.append(
                {
                    "role": role,
                    "reason": "这是你在求职偏好中填写的目标方向，仍需用已确认经历验证匹配度。",
                    "evidence_fact_ids": [],
                    "search_keywords": [role],
                }
            )
    if not suggestions:
        suggestions.append(
            {
                "role": "通用项目助理",
                "reason": "当前可用事实不足，仅提供宽泛探索方向，不能视为职业结论。",
                "evidence_fact_ids": [],
                "search_keywords": ["项目助理", "应届生"],
            }
        )
    categories = Counter(fact.category for fact in source)
    strengths = []
    if categories.get("education"):
        strengths.append("教育背景信息已被识别，可用于筛选学历或专业要求。")
    if categories.get("projects") or categories.get("employment"):
        strengths.append("已有项目或经历事实，可继续补充个人动作、方法与产出。")
    if categories.get("skills"):
        strengths.append("已有技能信息，可与岗位关键词逐项核对。")
    if not strengths:
        strengths.append("简历已完成文本解析，但还需要补充结构化事实。")
    pending = len(available) - len(confirmed)
    risks = []
    if pending:
        risks.append(f"仍有 {pending} 条事实未经用户确认，分析只可作为待核对建议。")
    if not categories.get("projects") and not categories.get("employment"):
        risks.append("缺少可核对的项目或工作经历，岗位匹配证据会偏弱。")
    missing = []
    if not categories.get("education"):
        missing.append("教育背景")
    if not categories.get("projects") and not categories.get("employment"):
        missing.append("项目或工作经历中的个人职责与产出")
    if not categories.get("skills"):
        missing.append("工具与技能熟练度")
    return {
        "summary": f"基于 {len(source)} 条{'已确认' if confirmed else '待确认'}事实，建议先探索 {suggestions[0]['role']} 等方向。",
        "strengths": strengths,
        "risks": risks,
        "role_suggestions": suggestions[:5],
        "missing_information": missing,
    }
