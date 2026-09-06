"""Build source-grounded target profiles from one or many JDs."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.entities import Job, TargetProfile, TargetProfileSource, User, now, uid
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import JobStructuredOutput
from app.services.job_access import visible_job
from app.services.quota_service import request_fingerprint

SINGLE_JD = "single_jd"
MULTI_JD = "multi_jd"
ALLOWED_MODES = {SINGLE_JD, MULTI_JD}
MIN_MULTI = 2
MAX_MULTI = 10
CATEGORY_PRIORITY = {
    "must_have": "high",
    "responsibility": "high",
    "nice_to_have": "medium",
    "keyword": "medium",
    "work_condition": "low",
}
FIELD_TO_CATEGORY = {
    "must_have_json": "must_have",
    "responsibilities_json": "responsibility",
    "nice_to_have_json": "nice_to_have",
    "keywords_json": "keyword",
    "work_conditions_json": "work_condition",
}


def normalize_requirement_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\s+", "", text).lower()
    return text


def evidence_in_jd(evidence: str, raw_jd: str) -> bool:
    snippet = str(evidence or "").strip()
    source = str(raw_jd or "")
    return bool(snippet) and snippet in source


def _requirement_id(category: str, text: str) -> str:
    digest = hashlib.sha256(f"{category}:{normalize_requirement_text(text)}".encode()).hexdigest()
    return digest[:16]


def _collect_job_items(job: Job) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for field, category in FIELD_TO_CATEGORY.items():
        for value in getattr(job, field, None) or []:
            text = str(value or "").strip()
            if text:
                items.append((category, text))
    return items


def _merge_requirement(
    buckets: dict[tuple[str, str], dict],
    *,
    category: str,
    text: str,
    job: Job,
    evidence: str,
) -> None:
    key = (category, normalize_requirement_text(text))
    if not key[1]:
        return
    row = buckets.get(key)
    source = {"job_id": job.id, "evidence": evidence}
    if row is None:
        buckets[key] = {
            "id": _requirement_id(category, text),
            "text": text,
            "category": category,
            "priority": CATEGORY_PRIORITY.get(category, "medium"),
            "frequency": 1,
            "sources": [source],
        }
        return
    row["frequency"] += 1
    if source not in row["sources"]:
        row["sources"].append(source)


def aggregate_jobs(jobs: list[Job], extra_items: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    buckets: dict[tuple[str, str], dict] = {}
    rejected: list[dict] = []
    jobs_by_id = {job.id: job for job in jobs}

    for job in jobs:
        for category, text in _collect_job_items(job):
            if evidence_in_jd(text, job.raw_jd):
                _merge_requirement(buckets, category=category, text=text, job=job, evidence=text)
            else:
                rejected.append(
                    {
                        "reason": "evidence_not_in_source_jd",
                        "category": category,
                        "requirement_id": _requirement_id(category, text),
                    }
                )

    for item in extra_items or []:
        category = str(item.get("category") or "must_have")
        text = str(item.get("text") or "").strip()
        job_id = str(item.get("job_id") or "")
        evidence = str(item.get("evidence") or text).strip()
        job = jobs_by_id.get(job_id)
        if not job or not evidence_in_jd(evidence, job.raw_jd):
            rejected.append(
                {
                    "reason": "unsupported_generated_requirement",
                    "category": category,
                    "requirement_id": _requirement_id(category, text) if text else "",
                }
            )
            continue
        _merge_requirement(buckets, category=category, text=text or evidence, job=job, evidence=evidence)

    requirements = sorted(
        buckets.values(),
        key=lambda row: (
            {"high": 0, "medium": 1, "low": 2}.get(row["priority"], 9),
            -row["frequency"],
            row["text"],
        ),
    )
    return requirements, rejected


async def _optional_model_requirements(jobs: list[Job]) -> list[dict]:
    extra: list[dict] = []
    for job in jobs:
        fallback = {
            "title": job.title,
            "company_name": job.company_name,
            "city": job.city,
            "responsibilities": list(job.responsibilities_json or []),
            "must_have": list(job.must_have_json or []),
            "nice_to_have": list(job.nice_to_have_json or []),
            "keywords": list(job.keywords_json or []),
            "work_conditions": list(job.work_conditions_json or []),
            "uncertain_fields": [],
        }
        try:
            structured, _provider = await generate_structured(
                task="target_profile",
                system_prompt=(
                    "你是岗位要求抽取助手。只提取输入 JD 中明确存在的职责、硬性要求、加分项、"
                    "关键词和工作条件；不得添加原文没有的要求。输出严格 JSON。"
                ),
                user_payload={"raw_jd": job.raw_jd, "mock_response": fallback},
                response_model=JobStructuredOutput,
            )
        except Exception:
            continue
        payload = structured.model_dump()
        mapping = {
            "must_have": "must_have",
            "responsibilities": "responsibility",
            "nice_to_have": "nice_to_have",
            "keywords": "keyword",
            "work_conditions": "work_condition",
        }
        for field, category in mapping.items():
            for text in payload.get(field) or []:
                extra.append(
                    {
                        "category": category,
                        "text": str(text),
                        "job_id": job.id,
                        "evidence": str(text),
                    }
                )
    return extra


def _title_for(mode: str, jobs: list[Job]) -> str:
    if mode == SINGLE_JD:
        job = jobs[0]
        return f"{job.company_name} · {job.title}"[:200]
    return f"{len(jobs)} 份 JD 聚合画像"[:200]


def dump_profile(profile: TargetProfile, sources: list[TargetProfileSource] | None = None) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "mode": profile.mode,
        "title": profile.title,
        "snapshot_json": profile.snapshot_json,
        "input_hash": profile.input_hash,
        "quality_metadata_json": profile.quality_metadata_json,
        "version": profile.version,
        "job_ids": [source.job_id for source in sources or []],
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def owned_profile(db: Session, user: User, profile_id: str) -> TargetProfile:
    row = db.scalar(
        select(TargetProfile).where(
            TargetProfile.id == profile_id,
            TargetProfile.user_id == user.id,
        )
    )
    if not row:
        raise AppError("TARGET_PROFILE_NOT_FOUND", "目标画像不存在。", 404)
    return row


def list_profile_sources(db: Session, profile_id: str) -> list[TargetProfileSource]:
    return list(
        db.scalars(
            select(TargetProfileSource).where(
                TargetProfileSource.target_profile_id == profile_id
            )
        )
    )


def refresh_profile_if_sources_changed(db: Session, profile: TargetProfile) -> TargetProfile:
    sources = list_profile_sources(db, profile.id)
    jobs = [db.get(Job, source.job_id) for source in sources]
    jobs = [job for job in jobs if job is not None]
    changed = False
    for source in sources:
        job = db.get(Job, source.job_id)
        if job is None:
            continue
        if job.raw_jd != source.raw_jd_snapshot:
            source.raw_jd_snapshot = job.raw_jd
            changed = True
    if not changed:
        return profile
    requirements, rejected = aggregate_jobs(jobs)
    profile.snapshot_json = {"requirements": requirements}
    profile.quality_metadata_json = {"rejected": rejected}
    profile.input_hash = request_fingerprint(
        {"mode": profile.mode, "job_ids": [job.id for job in jobs], "raw": [job.raw_jd for job in jobs]}
    )
    profile.version = int(profile.version or 1) + 1
    profile.updated_at = now()
    return profile


def _assert_job_ids_not_raw_jd(job_ids: list[str]) -> None:
    for job_id in job_ids:
        text = str(job_id or "")
        if "\n" in text or "\r" in text or len(text) > 80 or text.count(" ") >= 3:
            raise AppError(
                "JOB_ID_LOOKS_LIKE_JD",
                "岗位 ID 不能包含职位描述原文，请先把 JD 保存为岗位后再生成画像。",
                422,
            )


async def create_target_profile(db: Session, user: User, *, mode: str, job_ids: list[str]) -> TargetProfile:
    if mode not in ALLOWED_MODES:
        raise AppError("TARGET_PROFILE_MODE_INVALID", "目标画像只支持单 JD 或多 JD 模式。", 422)
    unique_ids = list(dict.fromkeys(str(item).strip() for item in job_ids if str(item).strip()))
    _assert_job_ids_not_raw_jd(unique_ids)
    if mode == SINGLE_JD and len(unique_ids) != 1:
        raise AppError("TARGET_PROFILE_JD_COUNT", "单 JD 画像必须恰好绑定一份岗位。", 422)
    if mode == MULTI_JD and not MIN_MULTI <= len(unique_ids) <= MAX_MULTI:
        raise AppError(
            "TARGET_PROFILE_JD_COUNT",
            f"多 JD 画像必须绑定 {MIN_MULTI} 到 {MAX_MULTI} 份岗位。",
            422,
        )
    jobs = [visible_job(db, user, job_id) for job_id in unique_ids]
    extra = await _optional_model_requirements(jobs)
    requirements, rejected = aggregate_jobs(jobs, extra)
    input_hash = request_fingerprint(
        {"mode": mode, "job_ids": unique_ids, "raw": [job.raw_jd for job in jobs]}
    )
    profile = TargetProfile(
        id=uid(),
        user_id=user.id,
        mode=mode,
        title=_title_for(mode, jobs),
        snapshot_json={"requirements": requirements},
        input_hash=input_hash,
        quality_metadata_json={"rejected": rejected},
        version=1,
    )
    db.add(profile)
    db.flush()
    for job in jobs:
        db.add(
            TargetProfileSource(
                id=uid(),
                target_profile_id=profile.id,
                job_id=job.id,
                raw_jd_snapshot=job.raw_jd,
            )
        )
    db.flush()
    return profile
