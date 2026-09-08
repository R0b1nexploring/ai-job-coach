"""Version-bound interview guides without practice workflows."""

from __future__ import annotations

from html import escape

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
from app.services.content_contract import visible_bullets


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
    targeted = _targeted_guide(version, bullets, profile=profile, facts=facts, bundle=bundle)
    fallback = _template_guide(version, bullets)
    content = fallback
    source = "fallback"
    provider_name = ""
    coverage_repaired = False
    try:
        mock = {
            "kind": version.kind,
            "cards": targeted.get("cards") or [],
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
                "为绑定的简历要点生成针对性面试准备材料。只使用输入的事实和目标要求，"
                "不得把未达成内容写成已完成。输出严格 JSON。"
            ),
            user_payload={
                "kind": version.kind,
                "headline": (version.content_json or {}).get("headline"),
                "profile_title": getattr(profile, "title", ""),
                "requirements": (bundle.target_snapshot_json or {}).get("requirements") or [],
                "facts": [
                    {
                        "id": fact.id,
                        "text": (fact.value_json or {}).get("text") or fact.source_text,
                        "organization": fact.organization,
                    }
                    for fact in facts
                ],
                "bullets": needed,
                "mock_response": mock,
            },
            response_model=InterviewGuideStructuredOutput,
        )
        modeled = structured.model_dump()
        modeled_ids = {str(card.get("bullet_id") or "") for card in modeled.get("cards") or []}
        coverage_repaired = any(str(bullet.get("id") or "") not in modeled_ids for bullet in needed)
        modeled["cards"] = _align_cards(
            needed,
            modeled.get("cards") or [],
            version.kind,
            profile=profile,
            facts=facts,
            bundle=bundle,
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
    if missing:
        guide.status = "queued"
        guide.quality_report_json = {
            "hard_passed": False,
            "coverage": 0,
            "issues": ["coverage_incomplete"],
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
        "practice_answers": False,
        "degraded": False,
    }


def _template_guide(version: ResumeVersion, bullets: list[dict]) -> dict:
    if version.kind == "submittable":
        cards = [_generic_claim_card(bullet) for bullet in bullets]
        return {
            "kind": "submittable",
            "cards": cards,
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
        "practice_answers": False,
        "degraded": True,
        "degraded_reason": "使用通用模板降级方案",
    }


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
