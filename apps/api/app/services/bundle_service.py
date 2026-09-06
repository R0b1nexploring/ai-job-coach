"""Create and generate paired resume bundles in-process."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.errors import AppError
from app.models.entities import (
    InterviewGuide,
    Resume,
    ResumeBundle,
    ResumeBundleRun,
    ResumeFact,
    ResumeVersion,
    TargetProfile,
    User,
    now,
    uid,
)
from app.providers.llm.base import ProviderError
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import ResumeBulletRewriteOutput, ResumeStructuredV3Output
from app.services.content_contract import (
    iter_bullets,
    new_bullet_id,
    normalize_bullet,
    validate_content,
    visible_bullets,
)
from app.services.experience_service import (
    confirmed_facts_for_generation,
    get_or_create_library_resume,
)
from app.services.quality_service import evaluate_version, evaluate_version_with_critic
from app.services.quota_service import change, request_fingerprint, was_created
from app.services.resume_template import (
    CATEGORY_SECTIONS,
    SECTION_ORDER,
    template_snapshot,
)
from app.services.target_profile_service import (
    list_profile_sources,
    owned_profile,
    refresh_profile_if_sources_changed,
)

RESUME_REWRITE_SYSTEM_PROMPT = (
    "你是中文校招/实习简历编辑。根据素材和目标画像生成简历，允许超出已确认事实扩写，"
    "补充岗位相关的经历要点、技能和成果，不因缺少事实来源而省略有用的建议。"
    "补充内容设置 verification_status=ai_generated、achieved=false，并记录 new_claims；"
    "有事实支持的条目设置 verification_status=source_based。不得编造来源 ID，"
    "source_fact_ids 和 requirement_ids 只能引用输入中的来源；没有来源可留空。"
    "蓝图未来项保留 achieved=false。不得把 AI 补充内容标成用户已核验事实。输出严格 JSON。"
)
RESUME_REWRITE_EXISTING_PROMPT = (
    "输入含 current_content 时，必须在现有简历上改写，不要退回原始事实清单或基础模板。"
    "scope=bullet 时只改进 focus_bullet_id 对应要点，保留其 id、来源字段和其余要点。"
    "scope=section 时只重写 focus_section_name，其余分区保持原结构。"
    "已有扩写内容和 AI 补充条目可以优化表达，不得整份还原成未改写的事实原文。"
)
_TERMINAL_BUNDLE_STATUSES = frozenset({"ready", "degraded", "failed"})


def dump_bundle(db: Session, bundle: ResumeBundle) -> dict:
    versions = list(
        db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == bundle.id))
    )
    guides = list(
        db.scalars(select(InterviewGuide).where(InterviewGuide.bundle_id == bundle.id))
    )
    run = db.get(ResumeBundleRun, bundle.id)
    status = _effective_bundle_status(bundle, run)
    return {
        "id": bundle.id,
        "status": status,
        "base_resume_id": bundle.base_resume_id,
        "target_profile_id": bundle.target_profile_id,
        "request_hash": bundle.request_hash,
        "generation_metadata_json": bundle.generation_metadata_json,
        "template_snapshot_json": {
            key: value
            for key, value in (bundle.template_snapshot_json or {}).items()
            if key != "private"
        },
        "versions": {
            version.kind: {
                "id": version.id,
                "status": version.guard_status,
                "kind": version.kind,
                "content_hash": version.content_hash,
                "unachieved_count": version.unachieved_count,
                "quality_status": (version.quality_report_json or {}).get("status"),
            }
            for version in versions
        },
        "guides": {
            guide.kind: {"id": guide.id, "status": guide.status}
            for guide in guides
        },
        "run": {
            "status": run.status if run else None,
            "claim_token": run.claim_token if run else None,
            "last_error": _safe_error(run.last_error if run else ""),
        },
        "error": _safe_error((bundle.generation_metadata_json or {}).get("error_message") or (run.last_error if run else "")),
        "can_retry": status in {"failed", "queued"},
        "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
        "updated_at": bundle.updated_at.isoformat() if bundle.updated_at else None,
    }


def owned_bundle(db: Session, user: User, bundle_id: str) -> ResumeBundle:
    row = db.scalar(
        select(ResumeBundle).where(
            ResumeBundle.id == bundle_id, ResumeBundle.user_id == user.id
        )
    )
    if not row:
        raise AppError("RESUME_BUNDLE_NOT_FOUND", "简历包不存在。", 404)
    return row


def _safe_error(message: str) -> str:
    text = str(message or "")
    for blocked in ("prompt", "raw_jd", "password", "api_key"):
        if blocked in text.lower():
            return "生成失败，请重试。"
    return text[:200]


def _fact_text(fact) -> str:
    return str((fact.value_json or {}).get("text") or fact.source_text or fact.label or "")


def _fact_input(fact) -> dict:
    return {
        "id": fact.id,
        "category": getattr(fact, "category", "") or "",
        "label": getattr(fact, "label", "") or "",
        "organization": getattr(fact, "organization", "") or "",
        "role_title": getattr(fact, "role_title", "") or "",
        "location": getattr(fact, "location", "") or "",
        "start_date": getattr(fact, "start_date", "") or "",
        "end_date": getattr(fact, "end_date", "") or "",
        "text": _fact_text(fact),
        "source_text": getattr(fact, "source_text", "") or "",
        "verification_status": getattr(fact, "verification_status", "") or "",
    }


def _requirement_input(requirement: dict) -> dict:
    return {
        "id": requirement.get("id"),
        "text": requirement.get("text"),
        "category": requirement.get("category"),
        "priority": requirement.get("priority"),
    }


def _generation_request_hash(*, resume_id: str, profile_id: str, profile_version, facts) -> str:
    return request_fingerprint(
        {
            "operation": "resume_bundle.create",
            "factuality_policy": "ai_expansion",
            "resume_id": resume_id,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "facts": [
                {
                    "id": fact.id,
                    "text": _fact_text(fact),
                    "updated_at": fact.updated_at.isoformat() if getattr(fact, "updated_at", None) else "",
                }
                for fact in sorted(facts, key=lambda item: item.id)
            ],
        }
    )


def _default_bundle_idempotency_key(*, user_id: str, resume_id: str, profile_id: str, payload_hash: str) -> str:
    return f"resume-bundle:{user_id}:{resume_id}:{profile_id}:{payload_hash}"


def _writer_source(provider_name: str) -> str:
    return "fallback" if provider_name == "mock_fallback" else "model"


def _effective_bundle_status(bundle: ResumeBundle, run: ResumeBundleRun | None) -> str:
    if bundle.status in _TERMINAL_BUNDLE_STATUSES:
        return bundle.status
    if run is not None and run.status in _TERMINAL_BUNDLE_STATUSES:
        return run.status
    return bundle.status


def _reconcile_bundle_run(db: Session, bundle: ResumeBundle) -> ResumeBundle:
    run = db.get(ResumeBundleRun, bundle.id)
    if run is None:
        return bundle
    if bundle.status in _TERMINAL_BUNDLE_STATUSES and run.status != bundle.status:
        run.status = bundle.status
        run.updated_at = now()
    elif run.status in _TERMINAL_BUNDLE_STATUSES and bundle.status != run.status:
        bundle.status = run.status
        bundle.updated_at = now()
    db.flush()
    return bundle


def resolve_generation_resume(db: Session, user: User, base_resume_id: str | None) -> Resume:
    if base_resume_id:
        resume = db.scalar(
            select(Resume).where(
                Resume.id == base_resume_id,
                Resume.user_id == user.id,
                Resume.deleted_at.is_(None),
            )
        )
        if not resume:
            raise AppError("RESUME_NOT_FOUND", "简历不存在。", 404)
        return resume
    return get_or_create_library_resume(db, user)


def create_bundle(
    db: Session,
    user: User,
    *,
    base_resume_id: str | None,
    target_profile_id: str,
    idempotency_key: str | None = None,
) -> ResumeBundle:
    resume = resolve_generation_resume(db, user, base_resume_id)
    profile = owned_profile(db, user, target_profile_id)
    refresh_profile_if_sources_changed(db, profile)
    facts = confirmed_facts_for_generation(db, user, resume)
    payload_hash = _generation_request_hash(
        resume_id=resume.id,
        profile_id=profile.id,
        profile_version=profile.version,
        facts=facts,
    )
    key = (idempotency_key or "").strip() or _default_bundle_idempotency_key(
        user_id=user.id,
        resume_id=resume.id,
        profile_id=profile.id,
        payload_hash=payload_hash,
    )
    existing = db.scalar(
        select(ResumeBundle).where(
            ResumeBundle.user_id == user.id,
            ResumeBundle.idempotency_key == key,
        )
    )
    if existing:
        if existing.request_hash and existing.request_hash != payload_hash:
            raise AppError("IDEMPOTENCY_KEY_REUSED", "同一幂等键不能用于不同的生成请求。", 409)
        return _reconcile_bundle_run(db, existing)
    ledger = change(
        db,
        user_id=user.id,
        quota_type="resume",
        delta=-1,
        reason="生成双轨简历包",
        idempotency_key=key,
        reference_type="resume_bundle",
        reference_id="",
        request_hash=payload_hash,
    )
    if not was_created(ledger) and ledger.reference_id:
        reused = db.get(ResumeBundle, ledger.reference_id)
        if reused:
            return _reconcile_bundle_run(db, reused)
    snapshot = template_snapshot()
    bundle = ResumeBundle(
        id=uid(),
        user_id=user.id,
        base_resume_id=resume.id,
        target_profile_id=profile.id,
        status="queued",
        facts_snapshot_json={
            "ids": [fact.id for fact in facts],
        },
        target_snapshot_json=deepcopy(profile.snapshot_json or {}),
        template_snapshot_json=snapshot,
        request_hash=payload_hash,
        idempotency_key=key,
        generation_metadata_json={"profile_version": profile.version},
    )
    db.add(bundle)
    db.flush()
    ledger.reference_id = bundle.id
    db.add(
        ResumeBundleRun(
            bundle_id=bundle.id,
            user_id=user.id,
            status="queued",
            request_hash=payload_hash,
        )
    )
    db.flush()
    return bundle


CLAIM_STALE_AFTER = timedelta(minutes=15)


def claim_bundle_run(db: Session, bundle_id: str, *, stale_after: timedelta | None = None) -> str | None:
    """Atomically claim a queued or stale generating run. Returns claim token or None."""
    token = uid()
    cutoff = now() - (stale_after or CLAIM_STALE_AFTER)
    result = db.execute(
        update(ResumeBundleRun)
        .where(
            ResumeBundleRun.bundle_id == bundle_id,
            or_(
                ResumeBundleRun.status == "queued",
                and_(
                    ResumeBundleRun.status == "generating",
                    ResumeBundleRun.updated_at <= cutoff,
                ),
            ),
        )
        .values(
            status="generating",
            claim_token=token,
            last_error="",
            updated_at=now(),
        )
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        return None
    bundle = db.get(ResumeBundle, bundle_id)
    if bundle is not None:
        bundle.status = "generating"
        bundle.updated_at = now()
    db.flush()
    return token


async def process_queued_bundles(db: Session, *, limit: int = 10) -> int:
    runs = list(
        db.scalars(
            select(ResumeBundleRun)
            .where(ResumeBundleRun.status.in_(["queued", "generating"]))
            .limit(limit)
        )
    )
    processed = 0
    for run in runs:
        claimed = await process_bundle(db, run.bundle_id)
        if claimed is not None:
            processed += 1
    return processed


async def process_bundle(db: Session, bundle_id: str) -> ResumeBundle | None:
    bundle = db.get(ResumeBundle, bundle_id)
    if bundle is None:
        raise AppError("RESUME_BUNDLE_NOT_FOUND", "简历包不存在。", 404)
    bundle = _reconcile_bundle_run(db, bundle)
    if bundle.status in {"ready", "degraded"}:
        return bundle
    token = claim_bundle_run(db, bundle_id)
    if token is None:
        db.refresh(bundle)
        _reconcile_bundle_run(db, bundle)
        return bundle if bundle.status in {"ready", "degraded", "generating", "failed"} else None
    inputs = _generation_inputs(db, bundle)
    db.commit()
    try:
        result = await _compose_pair(inputs)
    except Exception as exc:
        _mark_bundle_failed(db, bundle_id, token, exc)
        db.commit()
        return db.get(ResumeBundle, bundle_id)
    bundle = _apply_pair_result(db, bundle_id, token, result)
    db.commit()
    if bundle is not None and bundle.status in {"ready", "degraded"}:
        from app.services.interview_guide_service import generate_guides_for_bundle

        await generate_guides_for_bundle(db, bundle)
        db.commit()
    return db.get(ResumeBundle, bundle_id)


def requeue_bundle(db: Session, user: User, bundle_id: str) -> ResumeBundle:
    bundle = owned_bundle(db, user, bundle_id)
    if bundle.status not in {"failed", "queued"}:
        raise AppError("RESUME_BUNDLE_NOT_RETRYABLE", "只有失败或排队中的简历包可以重试。", 409)
    run = db.get(ResumeBundleRun, bundle.id)
    bundle.status = "queued"
    bundle.updated_at = now()
    if run is not None:
        run.status = "queued"
        run.last_error = ""
        run.updated_at = now()
    db.flush()
    return bundle


async def run_bundle_job(bundle_id: str) -> None:
    from app.database import make_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings

    engine = make_engine(get_settings().resolved_database_url())
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            await process_bundle(db, bundle_id)
            db.commit()
    finally:
        engine.dispose()


def _detached_fact(fact: ResumeFact) -> SimpleNamespace:
    return SimpleNamespace(
        id=fact.id,
        category=getattr(fact, "category", "") or "",
        label=getattr(fact, "label", "") or "",
        organization=getattr(fact, "organization", "") or "",
        role_title=getattr(fact, "role_title", "") or "",
        location=getattr(fact, "location", "") or "",
        start_date=getattr(fact, "start_date", "") or "",
        end_date=getattr(fact, "end_date", "") or "",
        value_json=deepcopy(fact.value_json or {}),
        source_text=getattr(fact, "source_text", "") or "",
        verification_status=getattr(fact, "verification_status", "") or "",
    )


def _generation_inputs(db: Session, bundle: ResumeBundle) -> dict:
    resume = db.get(Resume, bundle.base_resume_id)
    profile = db.get(TargetProfile, bundle.target_profile_id)
    sources = list_profile_sources(db, bundle.target_profile_id)
    facts = [
        db.get(ResumeFact, fact_id)
        for fact_id in (bundle.facts_snapshot_json or {}).get("ids") or []
    ]
    return {
        "bundle_id": bundle.id,
        "facts": [_detached_fact(fact) for fact in facts if fact is not None],
        "requirements": list((bundle.target_snapshot_json or {}).get("requirements") or []),
        "headline": profile.title if profile else "目标岗位",
        "contact": deepcopy(resume.contact_json) if resume and resume.contact_json else {},
        "job_id": sources[0].job_id if len(sources) == 1 else None,
        "snapshot": deepcopy(bundle.template_snapshot_json or template_snapshot()),
    }


def _mark_bundle_failed(db: Session, bundle_id: str, token: str, exc: Exception) -> None:
    bundle = db.get(ResumeBundle, bundle_id)
    run = db.get(ResumeBundleRun, bundle_id)
    if bundle is None or run is None or run.claim_token != token:
        return
    bundle.status = "failed"
    run.status = "failed"
    run.last_error = _safe_error(f"{type(exc).__name__}")
    bundle.generation_metadata_json = {
        **(bundle.generation_metadata_json or {}),
        "error": "generation_failed",
        "error_message": _safe_error(type(exc).__name__),
    }
    run.updated_at = now()
    bundle.updated_at = now()
    db.flush()


async def _compose_pair(inputs: dict) -> dict:
    facts = inputs["facts"]
    requirements = inputs["requirements"]
    headline = inputs["headline"]
    contact = inputs["contact"]
    degraded = False
    repair_history: list[str] = []
    submittable, sub_source = await _write_version(
        facts, requirements, kind="submittable", headline=headline, contact=contact
    )
    target, tgt_source = await _write_version(
        facts, requirements, kind="target", headline=headline, contact=contact
    )
    if sub_source == "fallback" or tgt_source == "fallback":
        degraded = True
        repair_history.append("model_unavailable_local_fallback")

    sub_report = await evaluate_version_with_critic(
        content=submittable, facts=facts, requirements=requirements, mode="submittable"
    )
    tgt_report = await evaluate_version_with_critic(
        content=target, facts=facts, requirements=requirements, mode="target"
    )
    for _round in range(2):
        if sub_report["hard_passed"] and tgt_report["hard_passed"]:
            break
        repair_history.append("quality_repair")
        if not sub_report["hard_passed"]:
            submittable = _fallback_version(
                facts, requirements, kind="submittable", headline=headline, contact=contact
            )
            sub_report = await evaluate_version_with_critic(
                content=submittable, facts=facts, requirements=requirements, mode="submittable"
            )
        if not tgt_report["hard_passed"]:
            target = _fallback_version(
                facts, requirements, kind="target", headline=headline, contact=contact
            )
            tgt_report = await evaluate_version_with_critic(
                content=target, facts=facts, requirements=requirements, mode="target"
            )
        degraded = True

    if not sub_report["hard_passed"]:
        return {
            "status": "failed",
            "repair_history": repair_history,
            "error": "hard_gates_failed",
            "submittable": submittable,
            "target": target,
            "sub_report": sub_report,
            "tgt_report": tgt_report,
            "sub_source": sub_source,
            "tgt_source": tgt_source,
        }

    status = "degraded" if degraded else "ready"
    if not tgt_report["hard_passed"]:
        status = "degraded"
        target = _omit_ungrounded_future(target)
        tgt_report = evaluate_version(
            content=target, facts=facts, requirements=requirements, mode="target"
        )
    return {
        "status": status,
        "repair_history": repair_history,
        "submittable": submittable,
        "target": target,
        "sub_report": sub_report,
        "tgt_report": tgt_report,
        "sub_source": sub_source,
        "tgt_source": tgt_source,
        "job_id": inputs.get("job_id"),
        "snapshot": inputs.get("snapshot") or template_snapshot(),
    }


def _apply_pair_result(db: Session, bundle_id: str, token: str, result: dict) -> ResumeBundle | None:
    bundle = db.get(ResumeBundle, bundle_id)
    run = db.get(ResumeBundleRun, bundle_id)
    if bundle is None:
        return None
    if run is not None and run.claim_token != token:
        return bundle
    repair_history = result.get("repair_history") or []
    if result.get("status") == "failed":
        bundle.status = "failed"
        bundle.generation_metadata_json = {
            "repair_history": repair_history,
            "error": result.get("error") or "hard_gates_failed",
        }
        if run is not None:
            run.status = "failed"
            run.updated_at = now()
        bundle.updated_at = now()
        db.flush()
        return bundle
    snapshot = result.get("snapshot") or bundle.template_snapshot_json or template_snapshot()
    job_id = result.get("job_id")
    _upsert_version(
        db,
        bundle,
        kind="submittable",
        content=result["submittable"],
        report=result["sub_report"],
        job_id=job_id,
        snapshot=snapshot,
        repair_history=repair_history,
    )
    _upsert_version(
        db,
        bundle,
        kind="target",
        content=result["target"],
        report=result["tgt_report"],
        job_id=job_id,
        snapshot=snapshot,
        repair_history=repair_history,
    )
    bundle.status = result["status"]
    bundle.generation_metadata_json = {
        "repair_history": repair_history,
        "degraded": bundle.status == "degraded",
        "writer": {
            "submittable": result.get("sub_source"),
            "target": result.get("tgt_source"),
        },
        "reviewer": {
            "submittable": (result.get("sub_report") or {}).get("reviewer"),
            "target": (result.get("tgt_report") or {}).get("reviewer"),
        },
    }
    if run is not None:
        run.status = bundle.status
        run.last_error = ""
        run.updated_at = now()
    bundle.updated_at = now()
    db.flush()
    return bundle


async def _write_version(
    facts,
    requirements,
    *,
    kind: str,
    headline: str,
    contact: dict,
    current_content: dict | None = None,
    scope: str = "all",
    focus_bullet_id: str | None = None,
    focus_section_name: str | None = None,
) -> tuple[dict, str]:
    fallback = _fallback_version(
        facts, requirements, kind=kind, headline=headline, contact=contact
    )
    keep_current = current_content is not None
    mock_source = current_content if keep_current else fallback
    try:
        mock = _schema_mock_content(mock_source, kind=kind, headline=headline, contact=contact)
    except Exception:
        mock = _schema_mock_content(fallback, kind=kind, headline=headline, contact=contact)
    prompt = RESUME_REWRITE_SYSTEM_PROMPT
    if keep_current:
        prompt = f"{prompt} {RESUME_REWRITE_EXISTING_PROMPT}"
    try:
        structured, provider_name = await generate_structured(
            task="resume_rewrite",
            system_prompt=prompt,
            user_payload={
                "kind": kind,
                "headline": headline,
                "contact": contact or {},
                "facts": [_fact_input(fact) for fact in facts],
                "requirements": [
                    _requirement_input(item) for item in requirements if isinstance(item, dict)
                ],
                "scope": scope,
                "focus_bullet_id": focus_bullet_id,
                "focus_section_name": focus_section_name,
                "current_content": current_content,
                "mock_response": mock,
            },
            response_model=ResumeStructuredV3Output,
        )
        content = structured.model_dump()
        content["content_version"] = 3
        content["factuality_policy"] = "ai_expansion"
        for section in content.get("sections") or []:
            for item in section.get("items") or []:
                bullets = []
                for bullet in item.get("bullets") or []:
                    try:
                        if not bullet.get("requirement_ids"):
                            bullet["requirement_ids"] = list(bullet.get("source_target_ids") or [])
                        bullets.append(
                            normalize_bullet(
                                {**bullet, "id": bullet.get("id") or new_bullet_id()},
                                default_achieved=kind == "submittable",
                            )
                        )
                    except AppError:
                        continue
                item["bullets"] = bullets
        content = _restore_bullet_ids(content, current_content)
        return validate_content(content), _writer_source(provider_name)
    except (ProviderError, AppError, Exception):
        if keep_current:
            return validate_content(deepcopy(current_content)), "fallback"
        return fallback, "fallback"


def _schema_mock_content(content: dict, *, kind: str, headline: str, contact: dict) -> dict:
    payload = {
        "content_version": 3,
        "kind": content.get("kind") or kind,
        "headline": content.get("headline") or headline,
        "contact": content.get("contact") or contact or {},
        "sections": content.get("sections") or [],
        "excluded_gaps": content.get("excluded_gaps") or [],
    }
    return ResumeStructuredV3Output.model_validate(payload).model_dump()


def _restore_bullet_ids(content: dict, previous: dict | None) -> dict:
    if not previous:
        return content
    previous_rows = list(iter_bullets(previous))
    current_rows = list(iter_bullets(content))
    if len(previous_rows) != len(current_rows):
        return content
    for (_section, _item, old_bullet), (_new_section, _new_item, new_bullet) in zip(
        previous_rows, current_rows
    ):
        if old_bullet.get("id"):
            new_bullet["id"] = old_bullet["id"]
            new_bullet["locked"] = bool(old_bullet.get("locked"))
    return content


def _fallback_version(facts, requirements, *, kind: str, headline: str, contact: dict) -> dict:
    grouped: dict[str, list] = {name: [] for name in SECTION_ORDER}
    for fact in facts:
        section = CATEGORY_SECTIONS.get(getattr(fact, "category", ""), "项目/科研/竞赛")
        text = _fact_text(fact)
        if not text:
            continue
        bullet = normalize_bullet(
            {
                "id": new_bullet_id(),
                "text": text[:120],
                "source_fact_ids": [fact.id],
                "source_target_ids": [],
                "requirement_ids": [],
                "achieved": True,
                "locked": False,
                "new_claims": [],
            }
        )
        item = {
            "organization": fact.organization,
            "role_title": fact.role_title,
            "location": fact.location,
            "start_date": fact.start_date,
            "end_date": fact.end_date,
            "bullets": [bullet],
        }
        grouped.setdefault(section, []).append(item)
    excluded = []
    if kind == "target" or not facts:
        fact_text = " ".join(
            str((fact.value_json or {}).get("text") or "") for fact in facts
        )
        future_items = []
        for requirement in requirements:
            text = str(requirement.get("text") or "")
            if not text or text in fact_text:
                continue
            if requirement.get("priority") != "high" and future_items:
                continue
            future_items.append(
                {
                    "organization": "",
                    "role_title": "目标补齐",
                    "location": "",
                    "start_date": "",
                    "end_date": "",
                    "bullets": [
                        normalize_bullet(
                            {
                                "id": new_bullet_id(),
                                "text": text[:120],
                                "source_fact_ids": [],
                                "source_target_ids": [requirement["id"]],
                                "requirement_ids": [requirement["id"]],
                                "achieved": False,
                                "locked": False,
                                "new_claims": [],
                            },
                            default_achieved=False,
                        )
                    ],
                }
            )
        if future_items:
            grouped["项目/科研/竞赛"].extend(future_items)
        cited_requirements = {
            req_id
            for item in sum(grouped.values(), [])
            for bullet in item.get("bullets") or []
            for req_id in bullet.get("requirement_ids") or []
        }
        for requirement in requirements:
            text = str(requirement.get("text") or "")
            if (
                requirement.get("priority") == "high"
                and requirement.get("id") not in cited_requirements
                and text
                and text not in fact_text
            ):
                excluded.append(text)
    sections = [
        {"name": name, "presentation": "tags" if name == "技能" else "items", "items": grouped[name]}
        for name in SECTION_ORDER
        if grouped.get(name)
    ]
    return validate_content(
        {
            "content_version": 3,
            "factuality_policy": "ai_expansion",
            "kind": kind,
            "headline": headline,
            "contact": contact or {},
            "sections": sections,
            "excluded_gaps": excluded,
        }
    )


def _omit_ungrounded_future(content: dict) -> dict:
    for section in content.get("sections") or []:
        items = []
        for item in section.get("items") or []:
            bullets = [
                bullet
                for bullet in item.get("bullets") or []
                if bullet.get("achieved") is not False
                or bullet.get("requirement_ids")
                or bullet.get("source_target_ids")
            ]
            if bullets:
                items.append({**item, "bullets": bullets})
        section["items"] = items
    content["sections"] = [section for section in content["sections"] if section.get("items")]
    return content


def _upsert_version(
    db: Session,
    bundle: ResumeBundle,
    *,
    kind: str,
    content: dict,
    report: dict,
    job_id: str | None,
    snapshot: dict,
    repair_history: list[str],
) -> ResumeVersion:
    content = validate_content(content)
    digest = request_fingerprint(content)
    report = {
        **report,
        "repair_history": repair_history,
        "content_hash": digest,
        "review_version": "v3-quality-1",
    }
    row = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.bundle_id == bundle.id, ResumeVersion.kind == kind
        )
    )
    if row is None:
        row = ResumeVersion(
            id=uid(),
            user_id=bundle.user_id,
            base_resume_id=bundle.base_resume_id,
            job_id=job_id,
            bundle_id=bundle.id,
            target_profile_id=bundle.target_profile_id,
            title=f"{content.get('headline') or '简历'} · {'求职简历' if kind == 'submittable' else '蓝图 Plus'}",
            kind=kind,
            content_json=content,
            traceability_json={"items": report.get("guard", {}).get("items") or []},
        )
        db.add(row)
    row.content_json = content
    row.traceability_json = {"items": report.get("guard", {}).get("items") or []}
    row.guard_status = "passed" if report.get("hard_passed") else "blocked"
    row.unachieved_count = int(report.get("unachieved_count") or 0)
    row.quality_report_json = _public_quality_report(report)
    row.content_hash = digest
    row.template_snapshot_json = snapshot
    row.review_status = "draft"
    row.updated_at = now()
    db.flush()
    return row


def _public_quality_report(report: dict) -> dict:
    return {
        "warnings": report.get("warnings") or [],
        "status": "passed" if report.get("hard_passed") else "blocked",
        "hard_passed": report.get("hard_passed"),
        "issues": report.get("issues") or [],
        "uncovered_requirements": report.get("uncovered_requirements") or [],
        "dimensions": report.get("dimensions") or {},
        "repair_history": report.get("repair_history") or [],
        "review_version": report.get("review_version"),
        "content_hash": report.get("content_hash"),
        "unachieved_count": report.get("unachieved_count") or 0,
        "reviewer": report.get("reviewer") or "deterministic",
        "reviewer_note": report.get("reviewer_note") or "",
    }


async def regenerate_scope(
    db: Session,
    user: User,
    bundle_id: str,
    *,
    version_id: str,
    scope: str,
    bullet_id: str | None = None,
    section_name: str | None = None,
) -> ResumeVersion:
    bundle = owned_bundle(db, user, bundle_id)
    version = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id,
            ResumeVersion.bundle_id == bundle.id,
            ResumeVersion.user_id == user.id,
        )
    )
    if not version:
        raise AppError("RESUME_VERSION_NOT_FOUND", "简历版本不存在。", 404)
    content = deepcopy(version.content_json or {})
    facts = [
        db.get(ResumeFact, fact_id)
        for fact_id in (bundle.facts_snapshot_json or {}).get("ids") or []
    ]
    facts = [fact for fact in facts if fact is not None]
    requirements = list((bundle.target_snapshot_json or {}).get("requirements") or [])
    locked_ids = {
        bullet.get("id")
        for _s, _i, bullet in iter_bullets(content)
        if bullet.get("locked")
    }
    headline = str(content.get("headline") or "")
    contact = content.get("contact") or {}
    if scope == "bullet" and bullet_id:
        if bullet_id in locked_ids:
            raise AppError("RESUME_BULLET_LOCKED", "已锁定要点不能重生成。", 409)
        await _replace_bullet_from_writer(
            content,
            facts=facts,
            requirements=requirements,
            kind=version.kind,
            headline=headline,
            contact=contact,
            bullet_id=bullet_id,
        )
    elif scope == "section" and section_name:
        rewritten, _source = await _write_version(
            facts,
            requirements,
            kind=version.kind,
            headline=headline,
            contact=contact,
            current_content=content,
            scope="section",
            focus_section_name=section_name,
        )
        _replace_section(content, rewritten, section_name, locked_ids)
    elif scope == "all":
        rewritten, _source = await _write_version(
            facts,
            requirements,
            kind=version.kind,
            headline=headline,
            contact=contact,
            current_content=content,
            scope="all",
        )
        content = _merge_locked(rewritten, content, locked_ids)
    else:
        raise AppError("REGENERATE_SCOPE_INVALID", "只支持按要点、分区或整份重生成。", 422)
    report = await evaluate_version_with_critic(
        content=content, facts=facts, requirements=requirements, mode=version.kind
    )
    snapshot = version.template_snapshot_json or bundle.template_snapshot_json
    old_hash = version.content_hash
    updated = _upsert_version(
        db,
        bundle,
        kind=version.kind,
        content=content,
        report=report,
        job_id=version.job_id,
        snapshot=snapshot,
        repair_history=["selective_regenerate"],
    )
    if updated.content_hash != old_hash:
        _stale_guides(db, updated)
    return updated


def lock_bullet(db: Session, user: User, version_id: str, bullet_id: str, locked: bool) -> ResumeVersion:
    version = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id, ResumeVersion.user_id == user.id
        )
    )
    if not version:
        raise AppError("RESUME_VERSION_NOT_FOUND", "简历版本不存在。", 404)
    found = False
    for _s, _i, bullet in iter_bullets(version.content_json or {}):
        if bullet.get("id") == bullet_id:
            bullet["locked"] = locked
            found = True
    if not found:
        raise AppError("RESUME_BULLET_NOT_FOUND", "要点不存在。", 404)
    flag_modified(version, "content_json")
    version.updated_at = now()
    db.flush()
    return version


async def _replace_bullet_from_writer(content, *, facts, requirements, kind, headline, contact, bullet_id):
    original = None
    for section, item, bullet in iter_bullets(content):
        if bullet.get("id") == bullet_id:
            original = (section, item, bullet)
            break
    if original is None:
        raise AppError("RESUME_BULLET_NOT_FOUND", "要点不存在。", 404)
    _section, item, bullet = original
    fact_ids = {str(value) for value in bullet.get("source_fact_ids") or []}
    req_ids = {
        str(value)
        for value in (bullet.get("requirement_ids") or []) + (bullet.get("source_target_ids") or [])
    }
    scoped_facts = [fact for fact in facts if str(fact.id) in fact_ids] if fact_ids else list(facts)
    scoped_requirements = (
        [requirement for requirement in requirements if str(requirement.get("id") or "") in req_ids]
        if req_ids
        else list(requirements)
    )
    mock = {
        "text": _mock_rewritten_text(str(bullet.get("text") or "")),
        "source_fact_ids": list(bullet.get("source_fact_ids") or []),
        "source_target_ids": list(bullet.get("source_target_ids") or []),
        "requirement_ids": list(bullet.get("requirement_ids") or []),
        "achieved": bool(bullet.get("achieved")),
        "new_claims": list(bullet.get("new_claims") or []),
        "verification_status": bullet.get("verification_status") or "ai_generated",
    }
    try:
        structured, _provider = await generate_structured(
            task="resume_rewrite",
            system_prompt=f"{RESUME_REWRITE_SYSTEM_PROMPT} {RESUME_REWRITE_EXISTING_PROMPT}",
            user_payload={
                "scope": "bullet",
                "kind": kind,
                "headline": headline,
                "contact": contact or {},
                "current_bullet": deepcopy(bullet),
                "experience": {
                    "organization": item.get("organization"),
                    "role_title": item.get("role_title"),
                    "location": item.get("location"),
                    "start_date": item.get("start_date"),
                    "end_date": item.get("end_date"),
                },
                "facts": [_fact_input(fact) for fact in scoped_facts],
                "requirements": [
                    _requirement_input(requirement)
                    for requirement in scoped_requirements
                    if isinstance(requirement, dict)
                ],
                "mock_response": mock,
            },
            response_model=ResumeBulletRewriteOutput,
        )
        incoming = normalize_bullet(
            {
                **bullet,
                "text": structured.text,
                "new_claims": list(structured.new_claims or bullet.get("new_claims") or []),
                "verification_status": structured.verification_status
                or bullet.get("verification_status")
                or "ai_generated",
            },
            default_achieved=kind == "submittable",
        )
    except (ProviderError, AppError, Exception):
        return
    incoming["id"] = bullet_id
    incoming["locked"] = bool(bullet.get("locked"))
    if fact_ids:
        incoming["source_fact_ids"] = list(fact_ids)
    if req_ids:
        incoming["requirement_ids"] = list(req_ids)
        incoming["source_target_ids"] = list(req_ids)
    bullets = item.get("bullets") or []
    for index, current in enumerate(bullets):
        if current.get("id") == bullet_id:
            bullets[index] = incoming
            break


def _mock_rewritten_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return "补充岗位相关的具体行动和结果。"
    if value.endswith("，并写清个人承担的步骤。"):
        return value
    return f"{value.rstrip('。.')}，并写清个人承担的步骤。"[:80]


def _select_rewritten_bullet(rewritten, *, original, original_index, original_count, fact_ids, req_ids):
    candidates = visible_bullets(rewritten)
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.get("id") and candidate.get("id") == original.get("id"):
            return candidate
    for candidate in candidates:
        candidate_facts = {str(value) for value in candidate.get("source_fact_ids") or []}
        candidate_reqs = {
            str(value)
            for value in (candidate.get("requirement_ids") or [])
            + (candidate.get("source_target_ids") or [])
        }
        if fact_ids and candidate_facts & fact_ids:
            return candidate
        if req_ids and candidate_reqs & req_ids:
            return candidate
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == original_count and 0 <= original_index < len(candidates):
        return candidates[original_index]
    return None


def _replace_section(content, replacement, section_name, locked_ids):
    original = next(
        (section for section in content.get("sections") or [] if section.get("name") == section_name),
        None,
    )
    incoming = next(
        (section for section in replacement.get("sections") or [] if section.get("name") == section_name),
        None,
    )
    if incoming is None:
        return
    if original is not None:
        incoming = _merge_locked(
            {"sections": [deepcopy(incoming)], "kind": content.get("kind")},
            {"sections": [original]},
            locked_ids,
        )["sections"][0]
    for index, section in enumerate(content.get("sections") or []):
        if section.get("name") == section_name:
            content["sections"][index] = incoming


def _merge_locked(replacement, original, locked_ids):
    if not locked_ids:
        return replacement
    locked_records = []
    for section in original.get("sections") or []:
        for item_index, item in enumerate(section.get("items") or []):
            for bullet_index, bullet in enumerate(item.get("bullets") or []):
                if bullet.get("id") in locked_ids:
                    locked_records.append(
                        {
                            "section": section.get("name"),
                            "item_index": item_index,
                            "bullet_index": bullet_index,
                            "item": {
                                "organization": item.get("organization"),
                                "role_title": item.get("role_title"),
                                "location": item.get("location"),
                                "start_date": item.get("start_date"),
                                "end_date": item.get("end_date"),
                            },
                            "bullet": deepcopy(bullet),
                        }
                    )
    for section in replacement.get("sections") or []:
        for item in section.get("items") or []:
            item["bullets"] = [
                bullet
                for bullet in item.get("bullets") or []
                if bullet.get("id") not in locked_ids
                and not any(
                    record["bullet"].get("text") == bullet.get("text")
                    and record["item"].get("organization") == item.get("organization")
                    and record["item"].get("role_title") == item.get("role_title")
                    for record in locked_records
                )
            ]
    replacement["sections"] = [
        section
        for section in replacement.get("sections") or []
        if any(item.get("bullets") for item in section.get("items") or [])
    ]
    for record in locked_records:
        section = next(
            (
                item
                for item in replacement.get("sections") or []
                if item.get("name") == record["section"]
            ),
            None,
        )
        if section is None:
            section = {
                "name": record["section"],
                "presentation": "items",
                "items": [],
            }
            replacement.setdefault("sections", []).append(section)
        item = next(
            (
                current
                for current in section.get("items") or []
                if current.get("organization") == record["item"].get("organization")
                and current.get("role_title") == record["item"].get("role_title")
            ),
            None,
        )
        if item is None:
            item = {**record["item"], "bullets": []}
            insert_at = min(record["item_index"], len(section.setdefault("items", [])))
            section["items"].insert(insert_at, item)
        bullets = item.setdefault("bullets", [])
        insert_at = min(record["bullet_index"], len(bullets))
        bullets.insert(insert_at, record["bullet"])
    order = {name: index for index, name in enumerate(SECTION_ORDER)}
    replacement["sections"] = sorted(
        replacement.get("sections") or [],
        key=lambda section: order.get(str(section.get("name") or ""), 99),
    )
    return replacement


def _stale_guides(db: Session, version: ResumeVersion) -> None:
    guides = list(
        db.scalars(
            select(InterviewGuide).where(InterviewGuide.resume_version_id == version.id)
        )
    )
    for guide in guides:
        guide.status = "stale"
        guide.updated_at = now()
