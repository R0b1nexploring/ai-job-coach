from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import InterviewStructuredOutput

from .claim_entities import corpus_contains, extract_claim_entities

PROJECT_CATEGORIES = {"projects", "employment"}
LEARNED_BACKGROUND = (
    "这是为达到岗位要求近期自主完成的学习项目，内容以可核对的过程记录和产出物为准。"
)
LEARNED_ROLE = "这是个人自主完成的学习练习，不代表公司、学校或团队项目经历。"
LEARNED_HONESTY = (
    "这是我为达到岗位要求最近自己做的学习项目，不是公司或校内课题；"
    "我会如实说明已经掌握的内容和仍需继续练习的边界。"
)
INTERVIEW_SYSTEM_PROMPT = (
    "你是模拟面试指南生成助手。题目只能依据输入 JD 与已审核简历。每个项目回答"
    "必须包含 background、my_role、actions、difficulties、result、verification 六部分，"
    "且逐条引用对应 fact。不得补充来源中没有的数字、工具、组织、团队规模或项目细节。"
    "learned 事实必须明确说是近期自主学习项目，提供 honesty_script，并至少生成一条"
    "高风险追问，回答策略要承认边界。fact_id 和 source_fact_ids 必须逐字选自输入允许的"
    "ID 列表，不得创建、缩写或改写 ID。每个项目回答中的数字、英文工具和证书词必须存在于"
    "该 fact_id 的 fact_claim_entity_allowlist；不在白名单中的实体必须完全省略。"
    "保留练习草稿免责声明。输出严格 JSON。"
)


def generate_questions(
    job,
    resume_content: dict | None = None,
    facts: list | None = None,
    targets: list | None = None,
    *,
    unachieved_count: int = 0,
) -> dict:
    """Generate a fact-linked, editable interview practice guide."""
    confirmed = [fact for fact in (facts or []) if fact.verification_status == "user_confirmed"]
    evidence = [_fact_evidence(fact) for fact in confirmed]
    if not evidence and resume_content:
        evidence = _resume_evidence(resume_content)

    resume_evidence = evidence[0]["text"][:40] if evidence else "简历中的相关经历"
    intro_parts = [item["text"] for item in evidence[:3]]
    intro = (
        f"您好，我应聘的是{job.title}。"
        + (
            "我的相关经历包括：" + "；".join(intro_parts) + "。"
            if intro_parts
            else "目前简历事实仍需补充，我会如实说明已有经历。"
        )
        + "我会结合岗位职责说明匹配点，并明确说明尚未接触的内容。"
    )
    projects = [
        item
        for item in evidence
        if item["category"] in PROJECT_CATEGORIES or item["provenance"] == "learned"
    ]
    project_answers = [_project_answer(item) for item in (projects or evidence[:1])[:5]]
    target_items = [
        str(getattr(target, "requirement", "") or getattr(target, "deliverable", "")).strip()
        for target in targets or []
        if getattr(target, "status", "pending") != "achieved"
    ][:unachieved_count]
    learned_count = sum(item["provenance"] == "learned" for item in evidence)

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
                "follow_ups": ["入职后如何验证自己的理解？"],
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
        "exposure_warning": {
            "unachieved_count": unachieved_count,
            "learned_count": learned_count,
            "message": (
                f"该版本包含 {unachieved_count} 条未达成目标和 {learned_count} 条新学经历；"
                "这些内容最可能在面试中被深挖，请明确区分目标、练习和已验证经历。"
            ),
            "items": target_items,
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
                "answer": "优势用已确认事实举例；不足选择真实且可改善的一项，并说明正在采取的真实行动。",
                "source_fact_ids": [item["id"] for item in evidence[:1] if item["id"]],
                "follow_ups": ["最近一次真实改进是什么？"],
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


async def generate_guarded_interview(
    job,
    resume_content: dict | None,
    confirmed_facts: list,
    targets: list | None = None,
    *,
    expected_unachieved_count: int = 0,
) -> dict:
    """Generate once, retry one semantic failure, then use the safe local guide."""
    interview_targets = list(targets or [])
    fallback = generate_questions(
        job,
        resume_content,
        confirmed_facts,
        interview_targets,
        unachieved_count=expected_unachieved_count,
    )
    payload = _interview_llm_payload(
        job,
        resume_content,
        confirmed_facts,
        interview_targets,
        expected_unachieved_count,
        fallback,
    )
    structured, provider_name = await generate_structured(
        task="interview_guide",
        system_prompt=INTERVIEW_SYSTEM_PROMPT,
        user_payload=payload,
        response_model=InterviewStructuredOutput,
    )
    content = _apply_grounded_interview_sections(structured.model_dump(), fallback)
    guide_status, guide_issues = guard_interview_guide(
        content,
        confirmed_facts,
        interview_targets,
        expected_unachieved_count=expected_unachieved_count,
    )
    semantic_retry_used = False
    semantic_retry_issues: list[str] = []
    if provider_name == "compatible" and guide_status == "blocked":
        semantic_retry_used = True
        semantic_retry_issues = list(guide_issues[:10])
        structured, provider_name = await generate_structured(
            task="interview_guide",
            system_prompt=(
                f"{INTERVIEW_SYSTEM_PROMPT}\n"
                "上一次结果未通过本地安全检查。请只依据 validation_feedback 修正规则问题；"
                "如果反馈指出无来源实体，必须将该实体完全删除，不得替换成另一个白名单外实体。"
                "不要复述或猜测上一次正文，仍须生成完整 JSON。"
            ),
            user_payload={
                **payload,
                "previous_output_rejected": True,
                "validation_feedback": semantic_retry_issues,
            },
            response_model=InterviewStructuredOutput,
        )
        content = _apply_grounded_interview_sections(structured.model_dump(), fallback)
        guide_status, guide_issues = guard_interview_guide(
            content,
            confirmed_facts,
            interview_targets,
            expected_unachieved_count=expected_unachieved_count,
        )

    fallback_used = provider_name != "compatible"
    model_validation_issues = list(guide_issues[:10]) if guide_status == "blocked" else []
    if guide_status == "blocked":
        content = fallback
        fallback_used = True
        guide_status, guide_issues = guard_interview_guide(
            content,
            confirmed_facts,
            interview_targets,
            expected_unachieved_count=expected_unachieved_count,
        )
    content.update(
        {
            "provider": provider_name,
            "fallback_used": fallback_used,
            "guide_guard_status": guide_status,
            "guide_guard_issues": guide_issues,
            "semantic_retry_used": semantic_retry_used,
            "semantic_retry_issues": semantic_retry_issues,
            "model_validation_issues": model_validation_issues,
            "deterministic_grounding_used": True,
        }
    )
    return content


def _apply_grounded_interview_sections(content: dict, fallback: dict) -> dict:
    """Keep all fact-bearing interview prose deterministic and source-linked."""
    grounded = dict(content)
    for field in (
        "self_introduction",
        "exposure_warning",
        "project_answers",
        "common_answers",
    ):
        grounded[field] = fallback[field]
    return grounded


def _interview_llm_payload(
    job,
    resume_content: dict | None,
    confirmed_facts: list,
    targets: list,
    expected_unachieved_count: int,
    fallback: dict,
) -> dict:
    available_fact_ids = [str(fact.id) for fact in confirmed_facts]
    project_fact_ids = [
        str(fact.id)
        for fact in confirmed_facts
        if fact.category in PROJECT_CATEGORIES or fact.provenance == "learned"
    ]
    fact_claim_entity_allowlist = {
        str(fact.id): list(
            dict.fromkeys(
                entity
                for text in (
                    str((fact.value_json or {}).get("text") or ""),
                    str(fact.source_text or ""),
                    str(getattr(fact, "organization", "") or ""),
                    str(getattr(fact, "role_title", "") or ""),
                    str(getattr(fact, "location", "") or ""),
                    str(getattr(fact, "start_date", "") or ""),
                    str(getattr(fact, "end_date", "") or ""),
                )
                for entity in extract_claim_entities(text)
            )
        )
        for fact in confirmed_facts
    }
    return {
        "job": {
            "title": job.title,
            "responsibilities": job.responsibilities_json,
            "must_have": job.must_have_json,
            "work_conditions": job.work_conditions_json,
        },
        "approved_resume": resume_content,
        "confirmed_facts": [
            {
                "id": fact.id,
                "category": fact.category,
                "value": fact.value_json,
                "source_text": fact.source_text,
                "provenance": fact.provenance,
            }
            for fact in confirmed_facts
        ],
        "capability_targets": [
            {
                "id": target.id,
                "requirement": target.requirement,
                "deliverable": target.deliverable,
                "status": target.status,
                "achieved_fact_id": target.achieved_fact_id,
            }
            for target in targets
        ],
        "expected_unachieved_count": expected_unachieved_count,
        "output_requirements": {
            "available_fact_ids": available_fact_ids,
            "project_fact_ids": project_fact_ids,
            "fact_claim_entity_allowlist": fact_claim_entity_allowlist,
            "project_answers_instruction": (
                "project_answers 的每个 fact_id 必须逐字选自 project_fact_ids；"
                "至少覆盖一个项目事实，不得为不存在的事实生成回答。"
            ),
            "source_ids_instruction": (
                "所有 source_fact_ids 必须逐字选自 available_fact_ids，不得编造 ID。"
            ),
            "claim_entities_instruction": (
                "每个 project_answer 只能使用其 fact_id 对应白名单中的数字、英文工具和证书词；"
                "不在白名单中的实体必须省略，不能根据常识补充。"
            ),
        },
        "mock_response": fallback,
    }


def guard_interview_guide(
    guide: dict,
    confirmed_facts: list,
    targets: list | None = None,
    *,
    expected_unachieved_count: int | None = None,
) -> tuple[str, list[str]]:
    """Verify each project answer against only its own fact and linked target."""
    facts_by_id = {
        str(fact.id): fact
        for fact in confirmed_facts
        if fact.verification_status == "user_confirmed"
    }
    targets_by_fact: dict[str, list] = {}
    for target in targets or []:
        if getattr(target, "achieved_fact_id", None):
            targets_by_fact.setdefault(str(target.achieved_fact_id), []).append(target)
    issues: list[str] = []

    if not guide.get("questions"):
        issues.append("面试指南缺少岗位问题")
    project_fact_ids = {
        str(fact.id)
        for fact in confirmed_facts
        if getattr(fact, "category", "") in PROJECT_CATEGORIES
        or getattr(fact, "provenance", "") == "learned"
    }
    answered_fact_ids = {
        str(entry.get("fact_id") or "") for entry in guide.get("project_answers") or []
    }
    if project_fact_ids and not project_fact_ids.intersection(answered_fact_ids):
        issues.append("面试指南缺少已确认项目事实的回答")

    warning = guide.get("exposure_warning") or {}
    if (
        expected_unachieved_count is not None
        and warning.get("unachieved_count") != expected_unachieved_count
    ):
        issues.append("面试暴露风险中的未达成条目数与简历版本不一致")

    for index, entry in enumerate(guide.get("project_answers") or []):
        fact_id = str(entry.get("fact_id") or "")
        fact = facts_by_id.get(fact_id)
        location = f"第 {index + 1} 个项目回答"
        if not fact:
            issues.append(f"{location}引用了未确认事实")
            continue
        provenance = str(getattr(fact, "provenance", "original_resume") or "original_resume")
        if entry.get("provenance") != provenance:
            issues.append(f"{location}的事实来源类型不一致")

        corpus = _fact_corpus(fact, targets_by_fact.get(fact_id, []))
        for text in _project_claim_texts(entry):
            for entity in extract_claim_entities(text):
                if not corpus_contains(corpus, entity):
                    issues.append(f"{location}包含无来源实体：{entity}")

        follow_ups = entry.get("follow_ups") or []
        if not follow_ups:
            issues.append(f"{location}缺少追问")
        if provenance == "learned":
            background = str((entry.get("structure") or {}).get("background") or "")
            honesty_script = str(entry.get("honesty_script") or "")
            if not honesty_script:
                issues.append(f"{location}缺少学习项目诚实说明")
            if not any(keyword in background for keyword in ("自主", "自学", "学习项目")):
                issues.append(f"{location}未如实标注为自主学习项目")
            organizations = [
                str(getattr(fact, "organization", "") or "").strip(),
                "公司项目",
                "校内课题",
                "学校项目",
            ]
            if any(value and value in background for value in organizations):
                issues.append(f"{location}把学习项目包装成组织项目")
            if not any(item.get("risk") == "high" for item in follow_ups):
                issues.append(f"{location}缺少高风险追问")

    return ("blocked" if issues else "passed", sorted(set(issues)))


def _fact_evidence(fact) -> dict:
    value = getattr(fact, "value_json", {}) or {}
    return {
        "id": str(fact.id),
        "text": str(value.get("text") or getattr(fact, "label", "") or ""),
        "category": str(getattr(fact, "category", "other") or "other"),
        "provenance": str(getattr(fact, "provenance", "original_resume") or "original_resume"),
        "source_text": str(getattr(fact, "source_text", "") or ""),
    }


def _resume_evidence(resume_content: dict) -> list[dict]:
    evidence = []
    for section in resume_content.get("sections") or []:
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            for bullet in item.get("bullets") or []:
                fact_ids = bullet.get("source_fact_ids") or []
                if bullet.get("text") and fact_ids:
                    evidence.append(
                        {
                            "id": str(fact_ids[0]),
                            "text": str(bullet["text"]),
                            "category": "resume",
                            "provenance": "original_resume",
                            "source_text": str(bullet["text"]),
                        }
                    )
    return evidence


def _project_answer(item: dict) -> dict:
    text = item["text"]
    learned = item["provenance"] == "learned"
    source_text = item["source_text"] or text
    return {
        "fact_id": item["id"],
        "provenance": item["provenance"],
        "question": f"请完整介绍这段经历：{text[:35]}",
        "structure": {
            "background": LEARNED_BACKGROUND if learned else f"背景与目标依据已确认事实：{text}",
            "my_role": LEARNED_ROLE if learned else f"我的职责边界以已确认记录为准：{text}",
            "actions": [f"已确认的过程记录：{text}"],
            "difficulties": "尚未记录可核对的困难与取舍；面试前只补充真实发生的内容。",
            "result": f"可核对产出：{text}",
            "verification": f"可核对来源：{source_text}",
        },
        "follow_ups": [
            {
                "question": "哪些部分是你亲自完成的，哪些内容尚未掌握？",
                "how_to_answer": "先承认能力边界，再依据已确认记录说明亲自完成的部分；没有记录的细节不猜测。",
                "risk": "high" if learned else "medium",
            },
            {
                "question": "结果可以通过什么材料核对？",
                "how_to_answer": f"只展示或说明已有来源记录：{source_text}",
                "risk": "medium",
            },
        ],
        "honesty_script": LEARNED_HONESTY if learned else "",
    }


def _fact_corpus(fact, linked_targets: list) -> str:
    fields = [
        str(getattr(fact, "value_json", {}) or {}),
        str(getattr(fact, "source_text", "") or ""),
        str(getattr(fact, "organization", "") or ""),
        str(getattr(fact, "role_title", "") or ""),
        str(getattr(fact, "location", "") or ""),
        str(getattr(fact, "start_date", "") or ""),
        str(getattr(fact, "end_date", "") or ""),
    ]
    for target in linked_targets:
        fields.extend(
            [
                str(getattr(target, "requirement", "") or ""),
                str(getattr(target, "deliverable", "") or ""),
                str(getattr(target, "evidence_text", "") or ""),
            ]
        )
    return " ".join(fields).casefold()


def _project_claim_texts(entry: dict) -> list[str]:
    structure = entry.get("structure") or {}
    values = [
        str(structure.get("background") or ""),
        str(structure.get("my_role") or ""),
        *(str(item) for item in structure.get("actions") or []),
        str(structure.get("difficulties") or ""),
        str(structure.get("result") or ""),
        str(structure.get("verification") or ""),
        str(entry.get("honesty_script") or ""),
    ]
    values.extend(str(item.get("how_to_answer") or "") for item in entry.get("follow_ups") or [])
    return values
