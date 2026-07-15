def generate_questions(job, resume_content: dict | None = None) -> dict:
    """Deterministic MVP question set; real providers must return the same schema."""
    resume_evidence = "相关项目"
    if resume_content:
        for section in resume_content.get("sections", []):
            items = section.get("items", []) if isinstance(section, dict) else []
            if items and isinstance(items[0], dict) and items[0].get("text"):
                resume_evidence = str(items[0]["text"])[:40]
                break
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
        ]
    }
