import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CapabilityTarget
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import CapabilityPlanOutput

logger = logging.getLogger("app.capability")


async def build_targets(match, job, facts: list) -> tuple[list[dict], str]:
    fallback = {"targets": [_fallback_target(gap, job.raw_jd) for gap in match.gaps_json or []]}
    fallback["targets"] = [item for item in fallback["targets"] if item["jd_evidence"]]
    structured, provider_name = await generate_structured(
        task="capability_plan",
        system_prompt=(
            "你是学习目标规划助手。每个目标必须对应输入 JD 中尚未满足的一项要求；"
            "jd_evidence 必须逐字引用 JD，deliverable 必须是可完成、可展示、可验收的产出物。"
            "不得把学习计划写成用户已经具备的能力。输出严格 JSON。"
        ),
        user_payload={
            "job": {"title": job.title, "raw_jd": job.raw_jd},
            "gaps": list(match.gaps_json or []),
            "confirmed_facts": [
                {
                    "id": fact.id,
                    "category": fact.category,
                    "text": fact.value_json.get("text", ""),
                }
                for fact in facts
                if fact.verification_status == "user_confirmed"
            ],
            "mock_response": fallback,
        },
        response_model=CapabilityPlanOutput,
    )
    targets = _validated_targets(structured.model_dump()["targets"], job)
    if not targets and fallback["targets"]:
        targets = _validated_targets(fallback["targets"], job)
        if provider_name == "compatible":
            provider_name = "mock_fallback"
    return targets, provider_name


def ensure_match_targets(db: Session, user, match, job) -> list[CapabilityTarget]:
    """Create JD-gap targets for a match if none exist yet, so blueprint resumes can show why."""
    existing = list(
        db.scalars(
            select(CapabilityTarget)
            .where(
                CapabilityTarget.match_id == match.id,
                CapabilityTarget.user_id == user.id,
            )
            .order_by(CapabilityTarget.created_at)
        )
    )
    if existing:
        return [row for row in existing if row.status != "achieved"]
    raw = [_fallback_target(gap, job.raw_jd) for gap in match.gaps_json or []]
    rows = []
    for item in _validated_targets(raw, job):
        row = CapabilityTarget(
            user_id=user.id,
            job_id=job.id,
            match_id=match.id,
            **item,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def _validated_targets(raw_targets: list[dict], job) -> list[dict]:
    targets = []
    for index, raw in enumerate(raw_targets[:20]):
        evidence = str(raw.get("jd_evidence") or "").strip()
        if not evidence or evidence not in job.raw_jd:
            logger.warning(
                "capability_target_discarded index=%d reason=jd_evidence_mismatch", index
            )
            continue
        requirement = str(raw.get("requirement") or "").strip()
        deliverable = str(raw.get("deliverable") or "").strip()
        if not requirement or not deliverable:
            logger.warning("capability_target_discarded index=%d reason=incomplete", index)
            continue
        criteria = [
            str(item).strip() for item in raw.get("acceptance_criteria") or [] if str(item).strip()
        ][:8]
        targets.append(
            {
                "requirement": requirement[:300],
                "category": _choice(
                    raw.get("category"), {"skills", "experience", "education", "projects"}, "skills"
                ),
                "severity": _choice(raw.get("severity"), {"low", "medium", "high"}, "medium"),
                "jd_evidence": evidence[:5000],
                "deliverable": deliverable[:5000],
                "acceptance_criteria_json": [item[:500] for item in criteria],
                "estimated_hours": max(1, min(int(raw.get("estimated_hours") or 1), 500)),
            }
        )
    return targets


def _fallback_target(gap: dict, raw_jd: str) -> dict:
    requirement = str(gap.get("requirement") or "").strip()
    evidence = _find_evidence(requirement, raw_jd)
    severity = str(gap.get("severity") or "medium")
    return {
        "requirement": requirement,
        "category": str(gap.get("category") or "skills"),
        "severity": severity,
        "jd_evidence": evidence,
        "deliverable": f"围绕“{requirement}”完成一个可展示练习，并保留过程记录与最终产物。",
        "acceptance_criteria": [
            "产出物可以独立打开或查看",
            "过程记录说明个人完成的步骤与取舍",
            "结果能够对应岗位要求逐项核对",
        ],
        "estimated_hours": 16 if severity == "high" else 8,
    }


def _find_evidence(requirement: str, raw_jd: str) -> str:
    candidates = [part.strip() for part in re.split(r"[\n。；;]", raw_jd) if part.strip()]
    direct = next((part for part in candidates if requirement and requirement in part), "")
    if direct:
        return direct
    tokens = [token for token in re.findall(r"[A-Za-z][\w+#.\-]*|[\u4e00-\u9fff]{2,}", requirement)]
    return next((part for part in candidates if any(token in part for token in tokens)), "")


def _choice(value, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default
