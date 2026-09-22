"""Version-bound interview guides without practice workflows."""

from __future__ import annotations

from html import escape
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.entities import (
    InterviewGuide,
    ResumeBundle,
    ResumeFact,
    ResumeVersion,
    TargetProfile,
    now,
    uid,
)
from app.providers.llm.base import ProviderError
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import InterviewGuideStructuredOutput
from app.services.content_contract import has_star_contract, iter_project_stories, visible_bullets


def queue_guides_for_bundle(db: Session, bundle: ResumeBundle) -> list[InterviewGuide]:
    versions = list(
        db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == bundle.id))
    )
    created = []
    for version in versions:
        if version.guard_status != "passed":
            continue
        guide = _upsert_guide(db, bundle, version)
        created.append(guide)
    db.flush()
    return created


def clone_guides_for_bundle(db: Session, parent: ResumeBundle, child: ResumeBundle) -> list[InterviewGuide]:
    """Bind the parent's verified guides to the child without a model call.

    Guides whose semantic hash still matches stay ready; a derived version with
    a changed hash gets a new stale guide that the user can regenerate.
    """
    parent_guides = list(
        db.scalars(select(InterviewGuide).where(InterviewGuide.bundle_id == parent.id))
    )
    child_versions = {
        version.kind: version
        for version in db.scalars(
            select(ResumeVersion).where(ResumeVersion.bundle_id == child.id)
        )
    }
    cloned = []
    for guide in parent_guides:
        version = child_versions.get(guide.kind)
        if version is None:
            continue
        same_hash = bool(guide.content_hash) and guide.content_hash == version.content_hash
        row = InterviewGuide(
            id=uid(),
            user_id=child.user_id,
            resume_version_id=version.id,
            target_profile_id=child.target_profile_id,
            bundle_id=child.id,
            kind=guide.kind,
            content_hash=version.content_hash,
            status="ready" if same_hash else "stale",
            content_json=deepcopy(guide.content_json or {}),
            quality_report_json=deepcopy(guide.quality_report_json or {}),
        )
        db.add(row)
        cloned.append(row)
    db.flush()
    return cloned


async def generate_guides_for_bundle(db: Session, bundle: ResumeBundle) -> list[InterviewGuide]:
    guides = queue_guides_for_bundle(db, bundle)
    profile = db.get(TargetProfile, bundle.target_profile_id)
    facts = [
        db.get(ResumeFact, fact_id)
        for fact_id in (bundle.facts_snapshot_json or {}).get("ids") or []
    ]
    facts = [fact for fact in facts if fact is not None]
    versions = {
        guide.id: db.get(ResumeVersion, guide.resume_version_id) for guide in guides
    }
    db.commit()
    for guide in guides:
        version = versions.get(guide.id)
        if version is None:
            continue
        await _fill_guide(db, guide, version, bundle=bundle, profile=profile, facts=facts)
    db.flush()
    return guides


async def regenerate_guide(db: Session, user, guide_id: str) -> InterviewGuide:
    guide = owned_guide(db, user, guide_id)
    bundle = db.get(ResumeBundle, guide.bundle_id) if guide.bundle_id else None
    version = db.get(ResumeVersion, guide.resume_version_id)
    if bundle is None or version is None:
        raise AppError("INTERVIEW_GUIDE_NOT_FOUND", "面试指南不存在。", 404)
    profile = db.get(TargetProfile, bundle.target_profile_id)
    facts = [
        db.get(ResumeFact, fact_id)
        for fact_id in (bundle.facts_snapshot_json or {}).get("ids") or []
    ]
    facts = [fact for fact in facts if fact is not None]
    guide.status = "queued"
    guide.content_hash = version.content_hash
    await _fill_guide(db, guide, version, bundle=bundle, profile=profile, facts=facts)
    db.flush()
    return guide


def _upsert_guide(db: Session, bundle: ResumeBundle, version: ResumeVersion) -> InterviewGuide:
    row = db.scalar(
        select(InterviewGuide).where(
            InterviewGuide.bundle_id == bundle.id,
            InterviewGuide.resume_version_id == version.id,
        )
    )
    if row is None:
        row = InterviewGuide(
            id=uid(),
            user_id=bundle.user_id,
            resume_version_id=version.id,
            target_profile_id=bundle.target_profile_id,
            bundle_id=bundle.id,
            kind=version.kind,
            content_hash=version.content_hash,
            status="queued",
            content_json={},
            quality_report_json={},
        )
        db.add(row)
        db.flush()
    row.content_hash = version.content_hash
    row.kind = version.kind
    return row


async def _fill_guide(db, guide: InterviewGuide, version: ResumeVersion, *, bundle, profile, facts) -> None:
    bullets = visible_bullets(version.content_json or {})
    needed = list(bullets)
    strategy = deepcopy((bundle.generation_metadata_json or {}).get("writing_brief") or {})
    writer_profile = deepcopy((bundle.generation_metadata_json or {}).get("writer_profile") or {})
    resource_boundary = writer_profile.get("resource_boundary") or {}
    targeted = _targeted_guide(version, bullets, profile=profile, facts=facts, bundle=bundle)
    needed_projects = list(iter_project_stories(version.content_json or {}))
    fallback = _template_guide(version, bullets, profile=profile, facts=facts, bundle=bundle)
    content = fallback
    source = "fallback"
    provider_name = ""
    coverage_repaired = False
    try:
        mock = {
            "kind": version.kind,
            "cards": targeted.get("cards") or [],
            "project_cards": targeted.get("project_cards") or [],
            "self_intro_60s": targeted.get("self_intro_60s") or "",
            "self_intro_90s": targeted.get("self_intro_90s") or "",
            "jd_questions": targeted.get("jd_questions") or [],
            "motivation": targeted.get("motivation") or "",
            "questions_to_ask": targeted.get("questions_to_ask") or [],
            "checklist": targeted.get("checklist") or [],
        }
        structured, provider_name = await generate_structured(
            task="interview_guide_v2",
            system_prompt=(
                "为绑定的简历要点生成针对性面试准备材料。只使用输入的事实、目标要求、"
                "写作策略与项目方案，沿用同一选材角度；不得独立重选岗位方向或加入正文未采用的成果，"
                "不得把未达成内容写成已完成，也不得为了补全讲解新增实验、专业仿真过程或结果。"
                "输出严格 JSON。"
            ),
            user_payload={
                "kind": version.kind,
                "headline": (version.content_json or {}).get("headline"),
                "profile_title": getattr(profile, "title", ""),
                "requirements": (bundle.target_snapshot_json or {}).get("requirements") or [],
                "writing_brief": {
                    "selected_materials": strategy.get("selected_materials") or [],
                    "per_job": strategy.get("per_job") or [],
                },
                "resource_boundary": resource_boundary,
                "facts": [
                    {
                        "id": fact.id,
                        "text": (fact.value_json or {}).get("text") or fact.source_text,
                        "organization": fact.organization,
                    }
                    for fact in facts
                ],
                "bullets": needed,
                "project_stories": [
                    {
                        "project_id": story.get("project_id"),
                        "title": story.get("title"),
                        "bullet_ids": story.get("bullet_ids") or [],
                        "situation": story.get("situation") or {},
                        "task": story.get("task") or {},
                        "actions": story.get("actions") or [],
                        "result": story.get("result") or {},
                        "achieved": story.get("achieved") is True,
                    }
                    for _section, _item, story in needed_projects
                ],
                "mock_response": mock,
            },
            response_model=InterviewGuideStructuredOutput,
        )
        modeled = structured.model_dump()
        modeled_ids = {str(card.get("bullet_id") or "") for card in modeled.get("cards") or []}
        modeled_project_ids = {
            str(card.get("project_id") or "") for card in modeled.get("project_cards") or []
        }
        malformed_projects = _missing_project_cards(
            needed_projects, modeled.get("project_cards") or []
        )
        coverage_repaired = (
            any(str(bullet.get("id") or "") not in modeled_ids for bullet in needed)
            or any(str(story.get("project_id") or "") not in modeled_project_ids for _section, _item, story in needed_projects)
            or bool(malformed_projects)
        )
        modeled["cards"] = _align_cards(
            needed,
            modeled.get("cards") or [],
            version.kind,
            profile=profile,
            facts=facts,
            bundle=bundle,
        )
        modeled["project_cards"] = _align_project_cards(
            needed_projects,
            modeled.get("project_cards") or [],
            version.kind,
            profile=profile,
        )
        modeled["practice_answers"] = False
        modeled["degraded"] = False
        modeled.pop("degraded_reason", None)
        content = modeled
        source = "model" if provider_name == "compatible" and not coverage_repaired else "deterministic"
    except (ProviderError, Exception):
        content = fallback
        source = "fallback"
    cards = content.get("cards") or []
    covered = {card.get("bullet_id") for card in cards}
    missing = [bullet["id"] for bullet in needed if bullet["id"] not in covered]
    if missing:
        content = fallback
        source = "fallback"
        cards = content.get("cards") or []
        covered = {card.get("bullet_id") for card in cards}
        missing = [bullet["id"] for bullet in needed if bullet["id"] not in covered]
    missing_projects = _missing_project_cards(needed_projects, content.get("project_cards") or [])
    if missing or missing_projects:
        guide.status = "queued"
        guide.quality_report_json = {
            "hard_passed": False,
            "coverage": 0,
            "issues": ["coverage_incomplete"] + (["project_coverage_incomplete"] if missing_projects else []),
            "source": source,
        }
        guide.content_json = content
        return
    unverified = {bullet["id"] for bullet in needed if bullet.get("verification_status") == "ai_generated"}
    for card in content.get("cards") or []:
        if card.get("bullet_id") in unverified:
            card["verification_status"] = "ai_generated"
            card["honest_boundary"] = "本条为 AI 扩写建议，请只陈述自己真正做过的部分，缺少的证据需要补齐。"
            card["achieved"] = False
            card["source_fact_ids"] = [
                fact_id
                for fact_id in (card.get("source_fact_ids") or [])
                if fact_id in {str(fact.id) for fact in facts or [] if fact is not None}
            ]
            if not card["source_fact_ids"]:
                card.pop("source_fact_ids", None)
                card["source_fact_ids"] = []
            card["danger"] = "不要把未完成或未经本人确认的内容说成已有经历。"
    content["degraded"] = source != "model"
    if source == "fallback":
        content["degraded_reason"] = "模型不可用，使用通用模板降级方案"
    elif source == "deterministic":
        content["degraded_reason"] = "未使用外部模型，使用确定性指南内容"
    guide.content_json = content
    guide.status = "ready"
    guide.content_hash = version.content_hash
    guide.quality_report_json = {
        "hard_passed": True,
        "coverage": 1,
        "issues": ["coverage_repaired"] if coverage_repaired else [],
        "project_coverage": 1 if needed_projects else None,
        "star_contract_version": 1 if has_star_contract(version.content_json or {}) else None,
        "content_hash": version.content_hash,
        "source": source,
        "reviewer_note": (
            "使用模型生成"
            if source == "model"
            else "模型不可用或未配置，使用确定性指南内容"
        ),
    }
    guide.updated_at = now()


def _guide_card(bullet: dict, *, kind: str, profile=None, facts=None, bundle=None) -> dict:
    if kind == "target" and bullet.get("achieved") is False:
        return _risk_card(bullet, profile=profile, bundle=bundle)
    return _claim_card(bullet, profile=profile, facts=facts, bundle=bundle)


def _targeted_guide(version: ResumeVersion, bullets: list[dict], *, profile, facts, bundle) -> dict:
    if version.kind == "submittable":
        cards = [
            _guide_card(bullet, kind=version.kind, profile=profile, facts=facts, bundle=bundle)
            for bullet in bullets
        ]
        title = getattr(profile, "title", "") or "目标岗位"
        fact_line = "、".join(
            str((fact.value_json or {}).get("text") or fact.source_text or "")[:40]
            for fact in facts[:2]
            if fact is not None
        )
        return {
            "kind": "submittable",
            "cards": cards,
            "project_cards": [],
            "self_intro_60s": (
                f"用 60 秒说明你为什么适合{title}，并点到已确认事实：{fact_line or '已确认项目经历'}。"
            ),
            "self_intro_90s": (
                f"用 90 秒补上教育或项目背景，以及你在{title}方向上已经亲手做过的部分。"
            ),
            "jd_questions": [
                f"结合{title}的职责，说明你做过的最接近工作。",
                "讲一次你独立排查问题的过程，只使用已确认事实。",
            ],
            "motivation": f"说明为什么{title}和你已确认的经历匹配。",
            "questions_to_ask": [f"{title}入职 90 天最希望独立承担哪件事？"],
            "checklist": ["核验材料带齐", "只陈述已确认事实", "未做过的内容直接说还没有"],
            "practice_answers": False,
            "degraded": False,
        }
    return {
        "kind": "target",
        "cards": [
            _guide_card(bullet, kind="target", profile=profile, facts=facts, bundle=bundle)
            for bullet in bullets
        ],
        "project_cards": _project_cards_for_version(version, profile=profile),
        "practice_answers": False,
        "degraded": False,
    }


def _template_guide(version: ResumeVersion, bullets: list[dict], *, profile=None, facts=None, bundle=None) -> dict:
    if version.kind == "submittable":
        cards = [_generic_claim_card(bullet) for bullet in bullets]
        return {
            "kind": "submittable",
            "cards": cards,
            "project_cards": [],
            "self_intro_60s": "用 60 秒说明求职方向、最能证明能力的一段经历，以及你能为岗位立刻承担的工作。",
            "self_intro_90s": "用 90 秒补上教育背景、一段项目或实习的个人边界，以及你希望在岗位上验证的方向。",
            "jd_questions": ["结合岗位职责说明你做过的最接近工作。", "讲一次你独立排查问题的过程。"],
            "motivation": "说明为什么这个岗位方向和你已确认的经历匹配。",
            "questions_to_ask": ["这个岗位入职 90 天最希望独立承担哪件事？"],
            "checklist": ["核验材料带齐", "只陈述已确认事实", "未做过的内容直接说还没有"],
            "degraded": True,
            "degraded_reason": "使用通用模板降级方案",
            "practice_answers": False,
        }
    return {
        "kind": "target",
        "cards": [
            _generic_risk_card(bullet) if bullet.get("achieved") is False else _generic_claim_card(bullet)
            for bullet in bullets
        ],
        "project_cards": _project_cards_for_version(version, profile=profile),
        "practice_answers": False,
        "degraded": True,
        "degraded_reason": "使用通用模板降级方案",
    }


def _project_cards_for_version(version: ResumeVersion, *, profile=None) -> list[dict]:
    return [
        _project_card(story, item=item, profile=profile)
        for _section, item, story in iter_project_stories(version.content_json or {})
    ]


def _align_project_cards(projects, cards: list[dict], kind: str, *, profile=None) -> list[dict]:
    """Keep one complete, correctly linked project card per saved STAR story."""
    by_id = {str(card.get("project_id") or ""): card for card in cards if isinstance(card, dict)}
    aligned = []
    for _section, item, story in projects:
        base = _project_card(story, item=item, profile=profile)
        modeled = by_id.get(str(story.get("project_id") or ""), {})
        if modeled.get("main_question"):
            base["main_question"] = str(modeled["main_question"])
        modeled_chains = modeled.get("follow_up_chains")
        if _valid_follow_up_chains(modeled_chains):
            base["follow_up_chains"] = modeled_chains
        if modeled.get("result_verification"):
            base["result_verification"] = str(modeled["result_verification"])
        if _nonempty_strings(modeled.get("knowledge_preparation")):
            base["knowledge_preparation"] = _nonempty_strings(modeled.get("knowledge_preparation"))
        if _nonempty_strings(modeled.get("practice_steps")):
            base["practice_steps"] = _nonempty_strings(modeled.get("practice_steps"))
        if str(modeled.get("purpose") or "").strip():
            base["purpose"] = str(modeled["purpose"])
        if _nonempty_strings(modeled.get("knowledge")):
            base["knowledge"] = _nonempty_strings(modeled.get("knowledge"))
        if _valid_practice_plan(modeled.get("practice_plan")):
            base["practice_plan"] = modeled["practice_plan"]
        if _nonempty_strings(modeled.get("deliverables")):
            base["deliverables"] = _nonempty_strings(modeled.get("deliverables"))
        if str(modeled.get("deliverable_check") or "").strip():
            base["deliverable_check"] = str(modeled["deliverable_check"])
        if _nonempty_strings(modeled.get("narrative")):
            base["narrative"] = _nonempty_strings(modeled.get("narrative"))
        if _nonempty_strings(modeled.get("questions")):
            base["questions"] = _nonempty_strings(modeled.get("questions"))
        if _nonempty_strings(modeled.get("answer_points")):
            base["answer_points"] = _nonempty_strings(modeled.get("answer_points"))
        # The id, story outline, evidence links and honest boundary always
        # come from the saved resume version, never from a guide model call.
        aligned.append(base)
    return aligned


def _missing_project_cards(projects, cards: list[dict]) -> list[str]:
    by_id = {str(card.get("project_id") or ""): card for card in cards if isinstance(card, dict)}
    missing = []
    for _section, _item, story in projects:
        project_id = str(story.get("project_id") or "")
        card = by_id.get(project_id)
        expected_bullet_ids = [str(value) for value in story.get("bullet_ids") or []]
        if not card or [str(value) for value in card.get("bullet_ids") or []] != expected_bullet_ids:
            missing.append(project_id)
            continue
        if not _valid_project_card(card):
            missing.append(project_id)
    return missing


def _project_card(story: dict, *, item: dict, profile=None) -> dict:
    title = str(story.get("title") or item.get("organization") or item.get("role_title") or "项目故事")
    situation = story.get("situation") or {}
    task = story.get("task") or {}
    actions = [action for action in story.get("actions") or [] if isinstance(action, dict)]
    result = story.get("result") or {}
    target_title = getattr(profile, "title", "") or "目标岗位"
    action_chains = []
    for index, action in enumerate(actions, start=1):
        step = str(action.get("step") or "这一步")
        method = str(action.get("method") or "所选方法")
        action_chains.append(
            {
                "anchor": f"行动 {index}",
                "question": f"在「{title}」里，你会怎样展开「{step}」？",
                "follow_ups": [
                    f"为什么选用「{method}」，而不是其他做法？",
                    f"遇到「{action.get('difficulty') or '约束与风险'}」时如何取舍？",
                    f"你本人/计划负责的边界「{action.get('contribution') or '待确认'}」如何证明？",
                ],
                "intent": "确认方法选择、技术判断和个人贡献边界。",
                "answer_points": [
                    step,
                    method,
                    str(action.get("rationale") or "说明方法与目标的关系"),
                ],
                "required_evidence": "过程记录、版本差异、设计说明或可演示交付物。",
                "common_mistakes": "只报工具名或团队结论，却说不清自己的步骤和取舍。",
            }
        )
    metrics = [metric for metric in result.get("metrics") or [] if isinstance(metric, dict)]
    metric_note = "；".join(
        f"{metric.get('name') or '指标'}：{metric.get('value') or '待记录'}（{metric.get('conditions') or '需说明口径'}）"
        for metric in metrics
    )
    achieved = story.get("achieved") is True
    assumptions = _nonempty_strings(story.get("design_assumptions"))
    open_questions = _nonempty_strings(story.get("open_questions"))
    preparation_questions = [
        f"「{question}」目前依据是什么，计划如何验证？" for question in open_questions
    ] + [
        f"「{assumption}」是设计假设还是个人既有经历，能否提供来源？" for assumption in assumptions
    ]
    boundary = ""
    if not achieved:
        boundary = "这是蓝图项目的准备方案；只能说明计划、验证方法与待补证据，不能说成自己已经完成。"
    chains = action_chains or [
        {
            "anchor": "项目方案",
            "question": "你会如何把目标拆成可验证的执行步骤？",
            "follow_ups": ["先验证哪个假设？", "如何留下过程证据？"],
            "intent": "确认是否有可执行的项目推进逻辑。",
            "answer_points": ["说明输入、输出、方法与验收条件"],
            "required_evidence": "过程记录与交付物。",
            "common_mistakes": "把待完成计划说成既有经历。",
        }
    ]
    deliverables = [str(value) for value in result.get("deliverables") or [] if str(value).strip()]
    return {
        "project_id": story.get("project_id"),
        "title": title,
        "bullet_ids": list(story.get("bullet_ids") or []),
        "star_outline": {
            "situation": situation,
            "task": task,
            "actions": actions,
            "result": result,
        },
        "design_assumptions": assumptions,
        "open_questions": open_questions,
        "preparation_questions": preparation_questions,
        "main_question": f"请用 STAR 讲清楚「{title}」如何证明你适合{target_title}。",
        "follow_up_chains": chains,
        "result_verification": (
            f"交付物：{'、'.join(deliverables) or '待明确'}。"
            f"验证：{result.get('verification_method') or '说明验收方式'}。"
            + (f" 指标口径：{metric_note}。" if metric_note else "")
        ),
        "knowledge_preparation": [
            "复盘每个方法的输入、输出、替代方案和取舍。",
            "准备一份可打开的交付物或过程证据，并说明它能验证什么。",
        ],
        "practice_steps": [
            "先用 90 秒按背景、任务、行动、结果完整讲一遍。",
            "再让同伴连续追问方法、难点、个人贡献和验证口径。",
        ],
        "achieved": achieved,
        "honest_boundary": boundary,
        **_practice_sections(
            title=title,
            target_title=target_title,
            task=task,
            actions=actions,
            result=result,
            deliverables=deliverables,
            metric_note=metric_note,
            assumptions=assumptions,
            open_questions=open_questions,
            preparation_questions=preparation_questions,
            chains=chains,
        ),
    }


def _practice_sections(
    *,
    title: str,
    target_title: str,
    task: dict,
    actions: list[dict],
    result: dict,
    deliverables: list[str],
    metric_note: str,
    assumptions: list[str],
    open_questions: list[str],
    preparation_questions: list[str],
    chains: list[dict],
) -> dict:
    """Versioned practice structure for a project card (schema_version=2).

    Older saved guides have none of these fields; the renderer and the API keep
    showing them by their original shape.
    """
    goal = str(task.get("goal") or f"交付{title}的可验证产物")
    purpose = (
        f"本项目的用途：用可检查的产物证明你能在{target_title}方向上{goal}。"
        "它不是为了堆经历，而是让面试官看到你的判断过程。"
    )
    knowledge = [
        f"理解「{action.get('method') or '所选方法'}」的适用条件、替代方案与取舍依据。"
        for action in actions
        if isinstance(action, dict) and str(action.get("method") or "").strip()
    ]
    knowledge.extend(
        f"先弄清「{question}」，否则无法说明结论是否可靠。" for question in open_questions
    )
    knowledge.extend(
        f"区分「{assumption}」是设计假设还是既有经历，并说明如何验证。"
        for assumption in assumptions
    )
    if not knowledge:
        knowledge = ["先明确项目的输入、约束与验收标准，再选择方法。"]
    practice_plan = []
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            continue
        practice_plan.append(
            {
                "action": f"第 {index} 步：{action.get('step') or '推进项目'}（{action.get('method') or '自选方法'}）",
                "artifact": str(action.get("contribution") or "过程记录或中间产物"),
                "check": str(
                    action.get("rationale")
                    or "对照任务目标检查这一步是否真的推进了交付物。"
                ),
            }
        )
    practice_plan.append(
        {
            "action": f"整理并交付：{'、'.join(deliverables) or f'{title}的产物'}",
            "artifact": "、".join(deliverables) or f"{title}的交付物",
            "check": str(
                result.get("verification_method") or "按验收清单逐项检查产物是否达标。"
            )
            + (f" 指标口径：{metric_note}。" if metric_note else ""),
        }
    )
    narrative = [
        f"背景：{str((task or {}).get('goal') or title)}",
        *[f"行动 {index}：{step}" for index, step in enumerate(_action_labels(actions), start=1)],
        f"结果：{'、'.join(deliverables) or '说明可检查的产物'}",
    ]
    questions = [str(chain.get("question") or "") for chain in chains if str(chain.get("question") or "")]
    questions.extend(preparation_questions)
    answer_points = [
        str(point)
        for chain in chains
        for point in chain.get("answer_points") or []
        if str(point).strip()
    ]
    return {
        "schema_version": 2,
        "purpose": purpose,
        "knowledge": knowledge,
        "practice_plan": practice_plan,
        "deliverables": deliverables,
        "deliverable_check": str(
            result.get("verification_method") or "按验收清单逐项检查产物是否达标。"
        ),
        "narrative": narrative,
        "questions": questions,
        "answer_points": answer_points,
    }


def _action_labels(actions: list[dict]) -> list[str]:
    return [
        f"{action.get('step') or '推进项目'}（{action.get('method') or '自选方法'}）"
        for action in actions
        if isinstance(action, dict)
    ]


def _nonempty_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _valid_follow_up_chains(values: object) -> bool:
    return isinstance(values, list) and bool(values) and all(
        isinstance(value, dict)
        and str(value.get("question") or "").strip()
        and _nonempty_strings(value.get("follow_ups"))
        and str(value.get("intent") or "").strip()
        and _nonempty_strings(value.get("answer_points"))
        for value in values
    )


def _valid_practice_plan(values: object) -> bool:
    return isinstance(values, list) and bool(values) and all(
        isinstance(value, dict)
        and str(value.get("action") or "").strip()
        and str(value.get("artifact") or "").strip()
        and str(value.get("check") or "").strip()
        for value in values
    )


def _valid_project_card(card: dict) -> bool:
    return bool(
        str(card.get("main_question") or "").strip()
        and isinstance(card.get("star_outline"), dict)
        and _valid_follow_up_chains(card.get("follow_up_chains"))
        and str(card.get("result_verification") or "").strip()
        and _nonempty_strings(card.get("knowledge_preparation"))
        and _nonempty_strings(card.get("practice_steps"))
    )


def _align_cards(
    needed: list[dict],
    cards: list[dict],
    kind: str,
    *,
    profile=None,
    facts=None,
    bundle=None,
) -> list[dict]:
    by_id = {str(card.get("bullet_id") or ""): card for card in cards}
    aligned = []
    for bullet in needed:
        card = by_id.get(str(bullet.get("id") or ""))
        if card is None:
            card = _guide_card(
                bullet,
                kind=kind,
                profile=profile,
                facts=facts or [],
                bundle=bundle,
            )
            card["degraded"] = True
        card["bullet_id"] = bullet.get("id")
        card["source_fact_ids"] = list(bullet.get("source_fact_ids") or [])
        card["requirement_ids"] = list(
            bullet.get("requirement_ids") or bullet.get("source_target_ids") or []
        )
        aligned.append(card)
    return aligned


def _claim_card(bullet: dict, *, profile=None, facts=None, bundle=None) -> dict:
    text = bullet.get("text") or ""
    title = getattr(profile, "title", "") or "目标岗位"
    fact_map = {str(fact.id): fact for fact in facts or [] if fact is not None}
    cited = [fact_map[item] for item in bullet.get("source_fact_ids") or [] if item in fact_map]
    fact_text = "；".join(
        str((fact.value_json or {}).get("text") or fact.source_text or "") for fact in cited
    )
    organization = "、".join(
        str(fact.organization or "") for fact in cited if getattr(fact, "organization", "")
    )
    return {
        "bullet_id": bullet.get("id"),
        "source_fact_ids": list(bullet.get("source_fact_ids") or []),
        "source_target_ids": list(bullet.get("source_target_ids") or []),
        "requirement_ids": list(bullet.get("requirement_ids") or []),
        "main_question": (
            f"结合{title}，请具体讲你在{organization or '这段经历'}中如何完成：{text}"
        ),
        "follow_ups": [
            f"你本人在「{fact_text or text}」里具体做了哪一步？",
            "用了什么已经出现在简历里的工具或方法？",
            "结果如何用已确认材料核验？",
        ],
        "six_part_story": {
            "context": f"{organization or '当时任务'}的背景",
            "goal": f"面向{title}要交付的结果",
            "action": text,
            "tools": "只提简历里出现的工具",
            "result": fact_text or "只提已确认结果",
            "learning": "可复用的方法，不编造业绩",
        },
        "personal_boundary": "只讲自己亲手做的部分，团队成果要标明边界。",
        "verification": "准备过程记录、代码/图纸/报告中能证明你参与的部分。",
        "danger": "不要把未确认数字、他人成果或蓝图目标说成已完成。",
    }


def _generic_claim_card(bullet: dict) -> dict:
    return {
        "bullet_id": bullet.get("id"),
        "source_fact_ids": list(bullet.get("source_fact_ids") or []),
        "source_target_ids": list(bullet.get("source_target_ids") or []),
        "requirement_ids": list(bullet.get("requirement_ids") or []),
        "main_question": "请介绍这段经历。",
        "follow_ups": ["你本人做了哪一步？", "用了什么工具或方法？", "结果如何核验？"],
        "six_part_story": {
            "context": "当时的任务背景",
            "goal": "要交付的结果",
            "action": "按简历要点说明行动",
            "tools": "只提简历里出现的工具",
            "result": "只提已确认结果",
            "learning": "可复用的方法，不编造业绩",
        },
        "personal_boundary": "只讲自己亲手做的部分，团队成果要标明边界。",
        "verification": "准备过程记录、代码/图纸/报告中能证明你参与的部分。",
        "danger": "不要把未确认数字、他人成果或蓝图目标说成已完成。",
        "degraded": True,
    }


def _risk_card(bullet: dict, *, profile=None, bundle=None) -> dict:
    text = bullet.get("text") or ""
    title = getattr(profile, "title", "") or "目标岗位"
    return {
        "bullet_id": bullet.get("id"),
        "requirement_ids": list(bullet.get("requirement_ids") or bullet.get("source_target_ids") or []),
        "achieved": False,
        "exposure_questions": [
            f"面向{title}，你真的完成过{text}吗？",
            "拿出当时的产出或证书，而不是目标描述。",
        ],
        "honest_boundary": f"目前还没有可核验经历支撑「{text}」，不能声称已经完成。",
        "missing_evidence": "完成后需要保留证书、项目记录或可演示产出。",
        "future_answer": "等补齐证据后，再用真实过程回答，而不是现在排练假经历。",
        "completed_as_done": False,
    }


def _generic_risk_card(bullet: dict) -> dict:
    return {
        "bullet_id": bullet.get("id"),
        "requirement_ids": list(bullet.get("requirement_ids") or bullet.get("source_target_ids") or []),
        "achieved": False,
        "exposure_questions": ["面试官可能追问你是否真正做过这件事。", "拿出当时的产出或证书。"],
        "honest_boundary": "目前还没有可核验经历，不能声称已经完成。",
        "missing_evidence": "完成后需要保留证书、项目记录或可演示产出。",
        "future_answer": "等补齐证据后，再用真实过程回答，而不是现在排练假经历。",
        "completed_as_done": False,
        "degraded": True,
    }


def owned_guide(db: Session, user, guide_id: str) -> InterviewGuide:
    row = db.scalar(
        select(InterviewGuide).where(
            InterviewGuide.id == guide_id, InterviewGuide.user_id == user.id
        )
    )
    if not row:
        raise AppError("INTERVIEW_GUIDE_NOT_FOUND", "面试指南不存在。", 404)
    return row


SIX_PART_LABELS = (
    ("context", "背景"),
    ("goal", "目标"),
    ("action", "行动"),
    ("tools", "工具"),
    ("result", "结果"),
    ("learning", "收获"),
)


def render_guide_html(guide: InterviewGuide) -> str:
    content = dict(guide.content_json or {})
    title = "蓝图风险指南" if guide.kind == "target" else "求职版作战指南"
    parts = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        f"<title>{escape(title)}</title>",
        "<style>body{font-family:sans-serif;max-width:720px;margin:24px auto;line-height:1.5;color:#111}",
        "h1,h2,h3{margin:1.2em 0 .4em}section{margin:1.5em 0;padding:1em;border:1px solid #ddd;border-radius:12px}",
        "ul{padding-left:1.2em}</style></head><body>",
        f"<h1>{escape(title)}</h1>",
    ]
    if content.get("self_intro_60s"):
        parts.append(_html_block("60 秒自我介绍", content.get("self_intro_60s")))
    if content.get("self_intro_90s"):
        parts.append(_html_block("90 秒自我介绍", content.get("self_intro_90s")))
    if content.get("motivation"):
        parts.append(_html_block("岗位动机", content.get("motivation")))
    if content.get("jd_questions"):
        parts.append(_html_list("JD 专业与行为题", content.get("jd_questions")))
    if content.get("questions_to_ask"):
        parts.append(_html_list("向面试官的反问", content.get("questions_to_ask")))
    if content.get("checklist"):
        parts.append(_html_list("面试前检查表", content.get("checklist")))
    for project_card in content.get("project_cards") or []:
        parts.append(_html_project_card(project_card))
    for card in content.get("cards") or []:
        parts.append(_html_card(card, kind=guide.kind))
    parts.append("</body></html>")
    return "".join(parts)


def _html_block(title: str, text: str) -> str:
    return f"<section><h2>{escape(title)}</h2><p>{escape(str(text or ''))}</p></section>"


def _html_list(title: str, items: list) -> str:
    rows = "".join(f"<li>{escape(str(item))}</li>" for item in items or [] if str(item).strip())
    return f"<section><h2>{escape(title)}</h2><ul>{rows}</ul></section>"


def _html_card(card: dict, *, kind: str) -> str:
    heading = card.get("main_question") or (card.get("exposure_questions") or [""])[0] or "要点准备"
    blocks = [f"<section><h2>{escape(str(heading))}</h2>"]
    if kind != "target" and card.get("follow_ups"):
        blocks.append("<h3>连续追问</h3><ul>")
        blocks.extend(f"<li>{escape(str(item))}</li>" for item in card.get("follow_ups") or [])
        blocks.append("</ul>")
    story = card.get("six_part_story") or {}
    if story:
        blocks.append("<h3>六段式讲法</h3><ul>")
        for key, label in SIX_PART_LABELS:
            if story.get(key):
                blocks.append(f"<li><strong>{escape(label)}</strong>：{escape(str(story[key]))}</li>")
        blocks.append("</ul>")
    for key, label in (
        ("personal_boundary", "个人贡献边界"),
        ("verification", "核验材料"),
        ("danger", "危险说法"),
        ("honest_boundary", "诚实边界"),
        ("missing_evidence", "缺少的证据"),
        ("future_answer", "补齐后的答法"),
    ):
        if card.get(key):
            blocks.append(f"<p><strong>{escape(label)}</strong>：{escape(str(card[key]))}</p>")
    if card.get("exposure_questions"):
        blocks.append("<h3>可能被问穿的问题</h3><ul>")
        blocks.extend(f"<li>{escape(str(item))}</li>" for item in card.get("exposure_questions") or [])
        blocks.append("</ul>")
    blocks.append("</section>")
    return "".join(blocks)


def _html_project_card(card: dict) -> str:
    title = str(card.get("title") or "项目 STAR 讲述")
    blocks = [f"<section><h2>{escape(title)} · STAR 讲述</h2>"]
    if card.get("schema_version") == 2:
        if card.get("purpose"):
            blocks.append(f"<p><strong>项目用途</strong>：{escape(str(card['purpose']))}</p>")
        if card.get("knowledge"):
            blocks.append("<h3>必要知识</h3><ul>")
            blocks.extend(f"<li>{escape(str(value))}</li>" for value in card["knowledge"])
            blocks.append("</ul>")
        if card.get("practice_plan"):
            blocks.append("<h3>操作步骤</h3><ol>")
            for step in card["practice_plan"]:
                if not isinstance(step, dict):
                    continue
                blocks.append(
                    "<li>"
                    f"{escape(str(step.get('action') or '推进项目'))}"
                    f"<br><em>预期产物</em>：{escape(str(step.get('artifact') or '过程记录'))}"
                    f"<br><em>检查方法</em>：{escape(str(step.get('check') or '对照目标检查'))}"
                    "</li>"
                )
            blocks.append("</ol>")
        if card.get("deliverables") or card.get("deliverable_check"):
            blocks.append("<h3>交付物与检查方法</h3><ul>")
            blocks.extend(f"<li>{escape(str(value))}</li>" for value in card.get("deliverables") or [])
            if card.get("deliverable_check"):
                blocks.append(f"<li><strong>检查方法</strong>：{escape(str(card['deliverable_check']))}</li>")
            blocks.append("</ul>")
        if card.get("narrative"):
            blocks.append("<h3>讲述框架</h3><ol>")
            blocks.extend(f"<li>{escape(str(value))}</li>" for value in card["narrative"])
            blocks.append("</ol>")
        if card.get("answer_points"):
            blocks.append("<h3>回答要点</h3><ul>")
            blocks.extend(f"<li>{escape(str(value))}</li>" for value in card["answer_points"])
            blocks.append("</ul>")
        if card.get("questions"):
            blocks.append("<h3>面试追问</h3><ul>")
            blocks.extend(f"<li>{escape(str(value))}</li>" for value in card["questions"])
            blocks.append("</ul>")
        if card.get("honest_boundary"):
            blocks.append(f"<p><strong>诚实边界</strong>：{escape(str(card['honest_boundary']))}</p>")
        blocks.append("</section>")
        return "".join(blocks)
    outline = card.get("star_outline") or {}
    situation = outline.get("situation") or {}
    task = outline.get("task") or {}
    result = outline.get("result") or {}
    blocks.append("<h3>背景与任务</h3><ul>")
    for label, value in (("背景", situation.get("context")), ("问题", situation.get("problem")), ("角色", task.get("role")), ("目标", task.get("goal"))):
        if value:
            blocks.append(f"<li><strong>{escape(label)}</strong>：{escape(str(value))}</li>")
    blocks.append("</ul>")
    actions = outline.get("actions") or []
    if actions:
        blocks.append("<h3>行动与技术取舍</h3><ul>")
        for action in actions:
            if not isinstance(action, dict):
                continue
            step = action.get("step") or "行动"
            method = action.get("method") or ""
            blocks.append(f"<li><strong>{escape(str(step))}</strong>：{escape(str(method))}</li>")
        blocks.append("</ul>")
    if result:
        blocks.append("<h3>结果与验证</h3><ul>")
        for deliverable in result.get("deliverables") or []:
            blocks.append(f"<li>{escape(str(deliverable))}</li>")
        if result.get("verification_method"):
            blocks.append(f"<li><strong>验证</strong>：{escape(str(result['verification_method']))}</li>")
        blocks.append("</ul>")
    if card.get("main_question"):
        blocks.append(f"<h3>主问题</h3><p>{escape(str(card['main_question']))}</p>")
    for chain in card.get("follow_up_chains") or []:
        if not isinstance(chain, dict):
            continue
        blocks.append(f"<h3>{escape(str(chain.get('anchor') or '连续追问'))}</h3>")
        if chain.get("question"):
            blocks.append(f"<p>{escape(str(chain['question']))}</p>")
        if chain.get("follow_ups"):
            blocks.append("<ul>")
            blocks.extend(f"<li>{escape(str(value))}</li>" for value in chain.get("follow_ups") or [])
            blocks.append("</ul>")
        for key, label in (("intent", "考察意图"), ("required_evidence", "需要的证据"), ("common_mistakes", "常见误区")):
            if chain.get(key):
                blocks.append(f"<p><strong>{escape(label)}</strong>：{escape(str(chain[key]))}</p>")
    if card.get("result_verification"):
        blocks.append(f"<p><strong>结果核验</strong>：{escape(str(card['result_verification']))}</p>")
    if card.get("knowledge_preparation"):
        blocks.append("<h3>知识准备</h3><ul>")
        blocks.extend(f"<li>{escape(str(value))}</li>" for value in card.get("knowledge_preparation") or [])
        blocks.append("</ul>")
    if card.get("practice_steps"):
        blocks.append("<h3>练习步骤</h3><ul>")
        blocks.extend(f"<li>{escape(str(value))}</li>" for value in card.get("practice_steps") or [])
        blocks.append("</ul>")
    if card.get("honest_boundary"):
        blocks.append(f"<p><strong>诚实边界</strong>：{escape(str(card['honest_boundary']))}</p>")
    blocks.append("</section>")
    return "".join(blocks)


def dump_guide(guide: InterviewGuide) -> dict:
    content = dict(guide.content_json or {})
    content.pop("model_prompt", None)
    return {
        "id": guide.id,
        "kind": guide.kind,
        "status": guide.status,
        "content_hash": guide.content_hash,
        "resume_version_id": guide.resume_version_id,
        "target_profile_id": guide.target_profile_id,
        "bundle_id": guide.bundle_id,
        "content_json": content,
        "quality_report_json": guide.quality_report_json,
        "practice_enabled": False,
        "scoring_enabled": False,
        "voice_enabled": False,
        "degraded": bool(content.get("degraded")),
        "degraded_reason": content.get("degraded_reason") or "",
    }
