from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.entities import (
    ExperienceEntry,
    InterviewGuide,
    Resume,
    ResumeBundle,
    ResumeFact,
    ResumeVersion,
    User,
    now,
    uid,
)
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import ResumeExtractionOutput
from app.services.resume_parser import build_missing_information

LIBRARY_PARSE_STATUS = "library"
LIBRARY_DISPLAY_NAME = "经历库"


def draft_materials_for_generation(db: Session, user: User) -> list[dict]:
    """Unconfirmed materials are copy references, not confirmed facts."""
    rows = list(
        db.scalars(
            select(ExperienceEntry).where(
                ExperienceEntry.owner_user_id == user.id,
                ExperienceEntry.status == "draft",
            )
        )
    )
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "title": row.title,
            "organization": row.organization,
            "role_title": row.role_title,
            "summary": row.summary,
            "details": row.details_json or {},
            "status": row.status,
        }
        for row in rows
    ]


def confirmed_facts_for_generation(db: Session, user: User, resume: Resume) -> list[ResumeFact]:
    """Use the selected resume facts plus the user's experience-library facts."""
    facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == resume.id,
                ResumeFact.user_id == user.id,
                ResumeFact.verification_status == "user_confirmed",
            )
        )
    )
    library = db.scalar(
        select(Resume).where(
            Resume.user_id == user.id,
            Resume.parse_status == LIBRARY_PARSE_STATUS,
            Resume.deleted_at.is_(None),
        )
    )
    if library and library.id != resume.id:
        seen = {fact.id for fact in facts}
        extras = list(
            db.scalars(
                select(ResumeFact).where(
                    ResumeFact.resume_id == library.id,
                    ResumeFact.user_id == user.id,
                    ResumeFact.verification_status == "user_confirmed",
                )
            )
        )
        facts.extend(fact for fact in extras if fact.id not in seen)
    return facts


ALLOWED_KINDS = {
    "education",
    "internship",
    "employment",
    "project",
    "research",
    "competition",
    "award",
    "certificate",
    "skill",
}
KIND_TO_CATEGORY = {
    "education": "education",
    "internship": "employment",
    "employment": "employment",
    "project": "projects",
    "research": "projects",
    "competition": "projects",
    "award": "certificates",
    "certificate": "certificates",
    "skill": "skills",
}
DETAIL_FIELDS = (
    "background",
    "goal",
    "ownership",
    "actions",
    "tools",
    "difficulties",
    "tradeoffs",
    "results",
    "metrics",
    "team_boundary",
    "verification",
)
KIND_ERROR = "素材类型需为教育、实习、工作、项目、科研、竞赛、奖项、证书或技能。"


def visible_experience_clause(user_id: str):
    from sqlalchemy import or_

    return or_(ExperienceEntry.owner_user_id.is_(None), ExperienceEntry.owner_user_id == user_id)


def get_or_create_library_resume(db: Session, user: User) -> Resume:
    row = db.scalar(
        select(Resume).where(
            Resume.user_id == user.id,
            Resume.parse_status == LIBRARY_PARSE_STATUS,
            Resume.deleted_at.is_(None),
        )
    )
    if row:
        return row
    row = Resume(
        user_id=user.id,
        original_file_key="library",
        original_media_type="application/x-experience-library",
        display_name=LIBRARY_DISPLAY_NAME,
        parse_status=LIBRARY_PARSE_STATUS,
        parsed_text="",
    )
    db.add(row)
    db.flush()
    return row


def list_experience(
    db: Session,
    user: User,
    *,
    kind: str = "",
    source: str = "",
) -> list[ExperienceEntry]:
    statement = select(ExperienceEntry).where(visible_experience_clause(user.id))
    if kind:
        statement = statement.where(ExperienceEntry.kind == kind)
    if source:
        statement = statement.where(ExperienceEntry.source == source)
    return list(db.scalars(statement.order_by(ExperienceEntry.updated_at.desc())))


def owned_experience(db: Session, user: User, entry_id: str) -> ExperienceEntry:
    row = db.scalar(
        select(ExperienceEntry).where(
            ExperienceEntry.id == entry_id,
            ExperienceEntry.owner_user_id == user.id,
        )
    )
    if not row:
        raise AppError("EXPERIENCE_NOT_FOUND", "经历不存在。", 404)
    return row


def visible_experience(db: Session, user: User, entry_id: str) -> ExperienceEntry:
    row = db.scalar(
        select(ExperienceEntry).where(
            ExperienceEntry.id == entry_id,
            visible_experience_clause(user.id),
        )
    )
    if not row:
        raise AppError("EXPERIENCE_NOT_FOUND", "经历不存在。", 404)
    return row


def create_user_experience(db: Session, user: User, data: dict) -> ExperienceEntry:
    kind = data["kind"]
    if kind not in ALLOWED_KINDS:
        raise AppError("EXPERIENCE_KIND_INVALID", KIND_ERROR, 422)
    title = (data.get("title") or "").strip()
    if not title:
        raise AppError("EXPERIENCE_TITLE_REQUIRED", "请填写经历标题。", 422)
    resume = get_or_create_library_resume(db, user)
    details = _details_dict(data.get("details_json"))
    entry = ExperienceEntry(
        id=uid(),
        owner_user_id=user.id,
        kind=kind,
        title=title[:200],
        organization=(data.get("organization") or "").strip()[:200],
        role_title=(data.get("role_title") or "").strip()[:200],
        location=(data.get("location") or "").strip()[:100],
        start_date=(data.get("start_date") or "").strip()[:10],
        end_date=(data.get("end_date") or "").strip()[:10],
        summary=(data.get("summary") or "").strip()[:5000],
        bullets_json=_string_list(data.get("bullets_json")),
        skills_json=_string_list(data.get("skills_json")),
        source="user_added",
        linked_resume_id=resume.id,
        details_json=details,
        clarifications_json=[],
        completeness_score=_completeness_score(details, data),
        status="draft",
        created_at=now(),
        updated_at=now(),
    )
    db.add(entry)
    db.flush()
    return entry


def update_user_experience(db: Session, user: User, entry_id: str, data: dict) -> ExperienceEntry:
    entry = owned_experience(db, user, entry_id)
    for field in (
        "title",
        "organization",
        "role_title",
        "location",
        "start_date",
        "end_date",
        "summary",
    ):
        if field in data and data[field] is not None:
            setattr(entry, field, str(data[field]).strip())
    if "bullets_json" in data and data["bullets_json"] is not None:
        entry.bullets_json = _string_list(data["bullets_json"])
    if "skills_json" in data and data["skills_json"] is not None:
        entry.skills_json = _string_list(data["skills_json"])
    if "details_json" in data and data["details_json"] is not None:
        merged = dict(entry.details_json or {})
        merged.update(_details_dict(data["details_json"]))
        entry.details_json = merged
    was_confirmed = entry.status == "confirmed" or bool(entry.linked_fact_id)
    entry.completeness_score = _completeness_score(entry.details_json, {
        "summary": entry.summary,
        "role_title": entry.role_title,
        "organization": entry.organization,
        "bullets_json": entry.bullets_json,
    })
    entry.updated_at = now()
    if was_confirmed:
        _unconfirm_material(db, user, entry)
    return entry


def copy_template(db: Session, user: User, template_id: str) -> ExperienceEntry:
    template = db.scalar(
        select(ExperienceEntry).where(
            ExperienceEntry.id == template_id,
            ExperienceEntry.owner_user_id.is_(None),
            ExperienceEntry.source == "template",
        )
    )
    if not template:
        raise AppError("EXPERIENCE_TEMPLATE_NOT_FOUND", "范本不存在。", 404)
    entry = ExperienceEntry(
        id=uid(),
        owner_user_id=user.id,
        kind=template.kind,
        title=template.title,
        organization="",
        role_title=template.role_title,
        location="",
        start_date="",
        end_date="",
        summary="",
        bullets_json=[],
        skills_json=list(template.skills_json or []),
        source="user_added",
        details_json={},
        clarifications_json=[],
        completeness_score=0,
        status="draft",
        created_at=now(),
        updated_at=now(),
    )
    db.add(entry)
    db.flush()
    return entry


def confirm_experience(db: Session, user: User, entry_id: str) -> ExperienceEntry:
    entry = owned_experience(db, user, entry_id)
    needs_org = entry.kind != "skill"
    if needs_org and not entry.organization.strip():
        raise AppError(
            "EXPERIENCE_INCOMPLETE",
            "请先填写真实组织名称和经历说明，不能直接把范本当成自己的经历。",
            422,
        )
    if not (entry.summary.strip() or entry.bullets_json or (entry.details_json or {}).get("actions")):
        raise AppError(
            "EXPERIENCE_INCOMPLETE",
            "请先填写真实组织名称和经历说明，不能直接把范本当成自己的经历。",
            422,
        )
    template_orgs = {
        row.organization
        for row in db.scalars(
            select(ExperienceEntry).where(
                ExperienceEntry.owner_user_id.is_(None),
                ExperienceEntry.source == "template",
            )
        )
        if row.organization
    }
    if entry.organization and entry.organization in template_orgs:
        raise AppError(
            "EXPERIENCE_TEMPLATE_COPY",
            "请把组织名称改成你自己的真实经历，不能沿用范本里的虚构单位。",
            422,
        )
    if entry.kind in {"award", "certificate"}:
        verification = str((entry.details_json or {}).get("verification") or "").strip()
        if not verification:
            raise AppError(
                "EXPERIENCE_EVIDENCE_REQUIRED",
                "奖项或证书需要提供本人核验信息后才能确认。",
                422,
            )
    resume = get_or_create_library_resume(db, user)
    entry.linked_resume_id = resume.id
    _replace_atomic_facts(db, user, resume, entry)
    entry.status = "confirmed"
    entry.updated_at = now()
    return entry


def delete_user_experience(db: Session, user: User, entry_id: str) -> None:
    entry = owned_experience(db, user, entry_id)
    if entry.linked_fact_id:
        fact = db.get(ResumeFact, entry.linked_fact_id)
        if fact and fact.user_id == user.id:
            fact.verification_status = "user_rejected"
            fact.confirmed_at = None
    db.delete(entry)


def sync_confirmed_facts_to_experience(db: Session, user: User, resume: Resume) -> None:
    if resume.parse_status == LIBRARY_PARSE_STATUS:
        return
    facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == resume.id,
                ResumeFact.user_id == user.id,
                ResumeFact.verification_status == "user_confirmed",
                ResumeFact.category.in_(["employment", "projects"]),
            )
        )
    )
    for fact in facts:
        kind = "internship" if fact.category == "employment" else "project"
        existing = db.scalar(
            select(ExperienceEntry).where(
                ExperienceEntry.owner_user_id == user.id,
                ExperienceEntry.linked_fact_id == fact.id,
            )
        )
        if existing:
            continue
        duplicate = db.scalar(
            select(ExperienceEntry).where(
                ExperienceEntry.owner_user_id == user.id,
                ExperienceEntry.kind == kind,
                ExperienceEntry.title == (fact.label or "")[:200],
                ExperienceEntry.organization == (fact.organization or ""),
            )
        )
        if duplicate:
            if not duplicate.linked_fact_id:
                duplicate.linked_fact_id = fact.id
            continue
        db.add(
            ExperienceEntry(
                owner_user_id=user.id,
                kind=kind,
                title=(fact.label or "未命名经历")[:200],
                organization=fact.organization or "",
                role_title=fact.role_title or "",
                location=fact.location or "",
                start_date=fact.start_date or "",
                end_date=fact.end_date or "",
                summary=str((fact.value_json or {}).get("text") or fact.source_text or ""),
                bullets_json=[],
                skills_json=[],
                source="original_resume",
                linked_resume_id=resume.id,
                linked_fact_id=fact.id,
            )
        )


def seed_templates(db: Session) -> int:
    existing = db.scalar(
        select(ExperienceEntry.id).where(
            ExperienceEntry.owner_user_id.is_(None),
            ExperienceEntry.source == "template",
        )
    )
    if existing:
        return 0
    templates = _template_rows()
    db.add_all(templates)
    db.flush()
    return len(templates)


def _details_dict(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {key: str(value.get(key) or "").strip() for key in DETAIL_FIELDS}


def _completeness_score(details: dict | None, data: dict | None = None) -> int:
    details = details or {}
    data = data or {}
    filled = 0
    total = len(DETAIL_FIELDS) + 3
    for key in DETAIL_FIELDS:
        if str(details.get(key) or "").strip():
            filled += 1
    if str(data.get("summary") or "").strip() or data.get("bullets_json"):
        filled += 1
    if str(data.get("organization") or "").strip():
        filled += 1
    if str(data.get("role_title") or "").strip():
        filled += 1
    return int(round(100 * filled / total))


def _claim_text(value: str) -> str:
    return str(value or "").strip()


def _replace_atomic_facts(
    db: Session,
    user: User,
    resume: Resume,
    entry: ExperienceEntry,
) -> None:
    existing = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.user_id == user.id,
                ResumeFact.material_id == entry.id,
            )
        )
    )
    for fact in existing:
        fact.verification_status = "user_rejected"
        fact.confirmed_at = None
    details = entry.details_json or {}
    claims: list[tuple[str, str]] = []
    if entry.organization:
        claims.append(("organization", entry.organization))
    if entry.role_title:
        claims.append(("role", entry.role_title))
    actions = details.get("actions") or "；".join(entry.bullets_json or []) or entry.summary
    if _claim_text(actions):
        claims.append(("action", _claim_text(actions)))
    if _claim_text(details.get("tools")):
        claims.append(("tool", _claim_text(details["tools"])))
    elif entry.skills_json:
        claims.append(("tool", "、".join(entry.skills_json)))
    result = details.get("results") or details.get("metrics")
    if _claim_text(result):
        claims.append(("result", _claim_text(result)))
    if _claim_text(details.get("ownership")):
        claims.append(("ownership", _claim_text(details["ownership"])))
    if not claims and entry.summary:
        claims.append(("action", entry.summary))
    created: list[ResumeFact] = []
    for claim_type, text in claims:
        fact = ResumeFact(
            resume_id=resume.id,
            user_id=user.id,
            created_by=user.id,
            category=KIND_TO_CATEGORY[entry.kind],
            label=entry.title[:200],
            organization=entry.organization,
            role_title=entry.role_title,
            location=entry.location,
            start_date=entry.start_date,
            end_date=entry.end_date,
            provenance="user_added",
            value_json={"text": text},
            source_text=text[:2000],
            verification_status="user_confirmed",
            confirmed_at=datetime.now(timezone.utc),
            material_id=entry.id,
            claim_type=claim_type,
            evidence_json={"material_id": entry.id, "claim_type": claim_type},
        )
        db.add(fact)
        created.append(fact)
    db.flush()
    if created:
        entry.linked_fact_id = created[0].id
    _refresh_library_missing(db, user, resume)


def _unconfirm_material(db: Session, user: User, entry: ExperienceEntry) -> None:
    facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.user_id == user.id,
                ResumeFact.material_id == entry.id,
            )
        )
    )
    if entry.linked_fact_id:
        linked = db.get(ResumeFact, entry.linked_fact_id)
        if linked and linked not in facts:
            facts.append(linked)
    fact_ids = {fact.id for fact in facts}
    for fact in facts:
        fact.verification_status = "extracted"
        fact.confirmed_at = None
        fact.updated_at = datetime.now(timezone.utc)
    entry.status = "draft"
    if not fact_ids:
        return
    versions = list(
        db.scalars(
            select(ResumeVersion).where(
                ResumeVersion.user_id == user.id,
                ResumeVersion.bundle_id.is_not(None),
            )
        )
    )
    stale_bundle_ids: set[str] = set()
    for version in versions:
        cited = {
            fact_id
            for section in (version.content_json or {}).get("sections", [])
            for item in section.get("items", [])
            for bullet in item.get("bullets", [])
            for fact_id in bullet.get("source_fact_ids") or []
        }
        if cited & fact_ids:
            version.guard_status = "stale"
            if version.bundle_id:
                stale_bundle_ids.add(version.bundle_id)
    for bundle_id in stale_bundle_ids:
        bundle = db.get(ResumeBundle, bundle_id)
        if bundle:
            bundle.status = "queued"
            bundle.updated_at = now()
    guides = list(
        db.scalars(select(InterviewGuide).where(InterviewGuide.user_id == user.id))
    )
    for guide in guides:
        if guide.bundle_id in stale_bundle_ids:
            guide.status = "stale"
            guide.updated_at = now()


def _refresh_library_missing(db: Session, user: User, resume: Resume) -> None:
    resume.missing_information_json = build_missing_information(
        list(
            db.scalars(
                select(ResumeFact).where(
                    ResumeFact.resume_id == resume.id,
                    ResumeFact.user_id == user.id,
                    ResumeFact.verification_status != "user_rejected",
                )
            )
        )
    )
    if not resume.missing_information_json:
        resume.facts_confirmed_at = datetime.now(timezone.utc)


async def generate_material_clarifications(
    db: Session, user: User, entry_id: str
) -> ExperienceEntry:
    entry = owned_experience(db, user, entry_id)
    details = entry.details_json or {}
    missing = [
        field
        for field in DETAIL_FIELDS
        if not str(details.get(field) or "").strip()
    ]
    questions = []
    if "ownership" in missing or not details.get("ownership"):
        questions.append(
            {
                "field": "ownership",
                "question": "这件事里你本人具体负责哪一段？和团队其他人的边界是什么？",
            }
        )
    for field in missing:
        if field == "ownership":
            continue
        labels = {
            "metrics": "有没有可核验的数字结果？没有就留空，不要估算。",
            "tools": "你实际使用过哪些工具或软件？",
            "results": "你亲手交付的结果是什么？",
            "verification": "有什么可以证明这是你本人完成的材料？",
        }
        if field in labels:
            questions.append({"field": field, "question": labels[field]})
    try:
        structured, _provider = await generate_structured(
            task="material_clarify",
            system_prompt="只针对缺失字段提问，不要替用户填写未知事实。输出严格 JSON。",
            user_payload={
                "material": {
                    "kind": entry.kind,
                    "title": entry.title,
                    "summary": entry.summary,
                    "details": details,
                    "missing": missing,
                },
                "mock_response": {
                    "contact": {},
                    "facts": [],
                    "missing_information": [
                        {"field": item["field"], "question": item["question"]}
                        for item in questions
                    ],
                },
            },
            response_model=ResumeExtractionOutput,
        )
        questions = [
            {"field": item.field, "question": item.question}
            for item in structured.missing_information
            if item.field in missing or not missing
        ] or questions
    except Exception:
        pass
    entry.clarifications_json = questions
    entry.status = "draft"
    entry.updated_at = now()
    return entry


def _sync_entry_to_fact(
    db: Session,
    user: User,
    resume: Resume,
    entry: ExperienceEntry,
) -> None:
    text = entry.summary.strip() or "；".join(entry.bullets_json or [])
    if not text:
        return
    category = KIND_TO_CATEGORY[entry.kind]
    fact = db.get(ResumeFact, entry.linked_fact_id) if entry.linked_fact_id else None
    if fact is None or fact.user_id != user.id:
        fact = ResumeFact(
            resume_id=resume.id,
            user_id=user.id,
            created_by=user.id,
            category=category,
            label=entry.title[:200],
            provenance="user_added",
        )
        db.add(fact)
        db.flush()
        entry.linked_fact_id = fact.id
    fact.label = entry.title[:200]
    fact.organization = entry.organization
    fact.role_title = entry.role_title
    fact.location = entry.location
    fact.start_date = entry.start_date
    fact.end_date = entry.end_date
    fact.value_json = {"text": text}
    fact.source_text = text[:2000]
    fact.verification_status = "user_confirmed"
    fact.confirmed_at = datetime.now(timezone.utc)
    fact.updated_at = datetime.now(timezone.utc)
    resume.missing_information_json = build_missing_information(
        list(
            db.scalars(
                select(ResumeFact).where(
                    ResumeFact.resume_id == resume.id,
                    ResumeFact.user_id == user.id,
                    ResumeFact.verification_status != "user_rejected",
                )
            )
        )
    )
    if not resume.missing_information_json:
        resume.facts_confirmed_at = datetime.now(timezone.utc)


def _string_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [item.strip() for item in re_split(value) if item.strip()][:20]
    return [str(item).strip() for item in value if str(item).strip()][:20]


def re_split(value: str) -> list[str]:
    import re

    return re.split(r"[\n；;]+", value)


def _template_rows() -> list[ExperienceEntry]:
    return [
        ExperienceEntry(
            owner_user_id=None,
            kind="internship",
            title="设备点检与保养实习",
            organization="示例智造装备股份有限公司",
            role_title="设备实习工程师",
            location="杭州",
            start_date="2025-07",
            end_date="2025-09",
            summary="在导师指导下完成产线设备点检、故障记录和保养计划整理，不包装成正式任职。",
            bullets_json=[
                "按点检表完成指定工位日常检查并记录异常",
                "整理故障现象、处理步骤和备件更换记录",
                "用 CAD 核对简单支架图纸与现场安装尺寸",
            ],
            skills_json=["设备点检", "CAD", "故障记录"],
            source="template",
        ),
        ExperienceEntry(
            owner_user_id=None,
            kind="project",
            title="小型装配体课程设计",
            organization="示例理工大学机电学院",
            role_title="课程项目负责人",
            location="杭州",
            start_date="2025-03",
            end_date="2025-06",
            summary="完成含多零件的课程装配体，输出工程图与爆炸图，属于课程项目而非公司项目。",
            bullets_json=[
                "完成 8 个以上零件的三维建模与装配",
                "检查干涉并输出带尺寸的工程图",
                "导出 STEP 与 PDF 作为验收材料",
            ],
            skills_json=["SolidWorks", "工程图", "装配体"],
            source="template",
        ),
        ExperienceEntry(
            owner_user_id=None,
            kind="internship",
            title="公用系统巡检实习",
            organization="虚构生物工程有限公司",
            role_title="公用系统实习生",
            location="苏州",
            start_date="2025-06",
            end_date="2025-08",
            summary="协助公用系统巡检和记录，明确为实习岗位，不写成正式工程师经历。",
            bullets_json=[
                "跟随师傅完成冷冻水与压缩空气点检",
                "把现场记录整理进巡检台账",
                "参与一次简单异常的原因讨论并复述处理边界",
            ],
            skills_json=["巡检", "台账", "公用系统"],
            source="template",
        ),
        ExperienceEntry(
            owner_user_id=None,
            kind="project",
            title="实验室管路布置练习",
            organization="示例生物医药工程教研组",
            role_title="课程练习",
            location="上海",
            start_date="2024-10",
            end_date="2024-12",
            summary="课程练习项目：完成实验室管路布置草图与材料清单，仅描述自己实际完成的部分。",
            bullets_json=[
                "根据给定平面图画主管与支管走向",
                "列出管件、支架和密封件清单",
                "说明自己负责的计算或绘图范围",
            ],
            skills_json=["管路布置", "材料清单"],
            source="template",
        ),
    ]
