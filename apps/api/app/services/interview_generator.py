from .claim_entities import corpus_contains, extract_claim_entities


def generate_questions(job, resume_content: dict | None = None, facts: list | None = None) -> dict:
    """Generate a fact-linked interview guide; it remains an editable practice draft."""
    confirmed = [fact for fact in (facts or []) if fact.verification_status == "user_confirmed"]
    evidence = [
        {
            "id": fact.id,
            "text": str(fact.value_json.get("text", fact.label)),
            "category": fact.category,
        }
        for fact in confirmed
    ]
    if not evidence and resume_content:
        for section in resume_content.get("sections", []):
            for item in section.get("items", []) if isinstance(section, dict) else []:
                if isinstance(item, dict) and item.get("text"):
                    evidence.append(
                        {
                            "id": str((item.get("source_fact_ids") or [""])[0]),
                            "text": str(item["text"]),
                            "category": "resume",
                        }
                    )
    resume_evidence = evidence[0]["text"][:40] if evidence else "简历中的相关经历"
    intro_parts = [item["text"] for item in evidence[:3]]
    intro = (
        f"您好，我应聘的是{job.title}。"
        + (
            "我的相关经历包括：" + "；".join(intro_parts) + "。"
            if intro_parts
            else "目前简历事实仍需补充，我会如实说明已有经历。"
        )
        + "我希望结合岗位职责进一步说明自己的匹配点，也会明确回答尚未接触的内容。"
    )
    projects = [item for item in evidence if item["category"] in {"projects", "employment"}]
    answer_evidence = projects or evidence[:1]
    project_answers = [
        {
            "question": f"请完整介绍这段经历：{item['text'][:35]}",
            "answer": (
                f"背景与目标：面试时先补充这段经历的真实背景。我的实际经历是：{item['text']}。"
                "个人行动：只展开自己确实完成的步骤。结果与复盘：说明可核对的产物，未知数字不要补写。"
            ),
            "source_fact_ids": [item["id"]],
            "follow_ups": ["你个人完成了哪一部分？", "遇到的困难和取舍是什么？", "结果如何核对？"],
        }
        for item in answer_evidence[:3]
    ]
    return {
        "questions": [
            {
                "id": "q1",
                "category": "resume_verification",
                "question": f"请说明你在“{resume_evidence}”中的个人职责。",
                "why_asked": "核实简历中的项目贡献",
                "rubric": ["职责清晰", "有事实依据", "不夸大"],
                "follow_ups": ["为什么这样选择？"],
            },
            {
                "id": "q2",
                "category": "job_knowledge",
                "question": f"你如何理解{job.title}的核心职责？",
                "why_asked": "检验岗位理解",
                "rubric": ["结合 JD", "结构完整"],
                "follow_ups": ["入职前三个月怎么做？"],
            },
            {
                "id": "q3",
                "category": "work_conditions",
                "question": "你如何评估岗位工作条件与个人偏好的匹配？",
                "why_asked": "确认稳定性和工作条件",
                "rubric": ["如实说明", "边界清晰"],
                "follow_ups": ["哪些条件需要进一步确认？"],
            },
        ],
        "self_introduction": {
            "duration_seconds": 90,
            "text": intro,
            "source_fact_ids": [item["id"] for item in evidence[:3] if item["id"]],
        },
        "project_answers": project_answers,
        "common_answers": [
            {
                "question": "为什么选择这个岗位？",
                "answer": f"先引用 JD 中{job.title}的明确职责，再用一条已确认经历说明匹配点；没有证据的能力不作承诺。",
                "source_fact_ids": [item["id"] for item in evidence[:1] if item["id"]],
                "follow_ups": ["你最看重哪项职责？", "哪些要求还需要学习？"],
            },
            {
                "question": "你的优势与不足是什么？",
                "answer": "优势用已确认事实举例；不足选择真实且可改善的一项，并说明正在采取的具体行动。",
                "source_fact_ids": [item["id"] for item in evidence[:1] if item["id"]],
                "follow_ups": ["最近一次改进是什么？"],
            },
        ],
        "preparation_plan": [
            "逐条打开公开岗位来源，核对职责、地点与发布时间。",
            "为每个简历要点准备背景、个人行动、产物和复盘，不补造数字。",
            "录音练习自我介绍并压缩到约 90 秒，删除无法追溯的表述。",
            "准备向面试官确认团队、考核目标、工作条件与招聘进度。",
        ],
        "risk_reminders": [
            "本文是练习草稿，不代表已验证的公司信息或标准答案。",
            "遇到未做过的工具或项目要明确说明，不要把团队成果写成个人成果。",
            "薪资、工作地点和工作条件以企业正式沟通为准。",
        ],
    }


def guard_interview_guide(guide: dict, confirmed_facts: list) -> tuple[str, list[str]]:
    allowed_ids = {str(fact.id) for fact in confirmed_facts}
    allowed_text = " ".join(str(fact.value_json) for fact in confirmed_facts).lower()
    issues = []
    entries = [guide.get("self_introduction", {}), *guide.get("project_answers", [])]
    for entry in entries:
        ids = {str(value) for value in entry.get("source_fact_ids", []) if value}
        if ids and not ids.issubset(allowed_ids):
            issues.append("面试稿引用了未确认事实")
        text = str(entry.get("text") or entry.get("answer") or "")
        for entity in extract_claim_entities(text):
            if not corpus_contains(allowed_text, entity):
                issues.append(entity)
    return ("blocked" if issues else "passed", sorted(set(issues)))
