from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import can_access_user, require_roles
from app.errors import AppError
from app.models.entities import (
    AdvisorAssignment,
    Application,
    AuditLog,
    Interview,
    Job,
    Match,
    Order,
    Package,
    QuotaLedger,
    Resume,
    ResumeFact,
    ResumeVersion,
    User,
    UserProfile,
)
from app.providers.storage.local import LocalStorage
from app.services.maintenance_service import run_maintenance
from app.services.privacy_service import purge_user_data
from app.services.provider_status import provider_status
from app.services.quota_service import change, request_fingerprint, was_created
from app.services.report_service import weekly_report

from .common import dump, listed

router = APIRouter(prefix="/api/advisor", tags=["advisor"])


def assigned_ids(db, actor):
    if actor.role == "admin":
        return list(db.scalars(select(User.id).where(User.role == "user")))
    return list(
        db.scalars(
            select(AdvisorAssignment.user_id).where(
                AdvisorAssignment.advisor_id == actor.id, AdvisorAssignment.status == "active"
            )
        )
    )


@router.get("/queues")
async def queues(
    actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)
):
    ids = assigned_ids(db, actor)
    labels = [
        "新线索",
        "待咨询",
        "待付款",
        "待核实",
        "待修改",
        "待投递",
        "有面试",
        "待复盘",
        "退款/争议",
    ]
    tasks = {label: [] for label in labels}
    users = {row.id: row for row in db.scalars(select(User).where(User.id.in_(ids)))}
    package_names = {}
    for order in db.scalars(
        select(Order).where(Order.user_id.in_(ids)).order_by(Order.created_at.desc())
    ):
        package_names.setdefault(
            order.user_id,
            str((order.package_snapshot_json or {}).get("name") or "演示额度"),
        )

    def context(user_id: str, due_at=None):
        owner = users.get(user_id)
        return {
            "user_name": owner.display_name if owner else "未知用户",
            "package_name": package_names.get(user_id, "演示额度"),
            "due_at": due_at,
        }

    for version in db.scalars(
        select(ResumeVersion).where(
            ResumeVersion.user_id.in_(ids),
            or_(
                ResumeVersion.guard_status == "blocked",
                ResumeVersion.review_status == "advisor_review",
            ),
        )
    ):
        tasks["待核实" if version.guard_status == "blocked" else "待修改"].append(
            {
                "id": version.id,
                "user_id": version.user_id,
                "type": "resume",
                "risk": "high" if version.guard_status == "blocked" else "medium",
                "next_action": "核查事实" if version.guard_status == "blocked" else "审核简历",
                "can_review": version.guard_status == "passed"
                and version.review_status == "advisor_review",
                **context(version.user_id),
            }
        )
    for app in db.scalars(
        select(Application).where(
            Application.user_id.in_(ids),
            Application.status.in_(["pending_confirmation", "ready_to_apply"]),
        )
    ):
        tasks["待投递"].append(
            {
                "id": app.id,
                "user_id": app.user_id,
                "type": "application",
                "risk": "low",
                "next_action": "确认并投递",
                **context(app.user_id, app.next_action_at),
            }
        )
    for interview in db.scalars(
        select(Interview).where(
            Interview.user_id.in_(ids), Interview.status.in_(["draft", "submitted"])
        )
    ):
        tasks["有面试" if interview.status == "draft" else "待复盘"].append(
            {
                "id": interview.id,
                "user_id": interview.user_id,
                "type": "interview",
                "risk": "medium",
                "next_action": "等待用户作答" if interview.status == "draft" else "评分复盘",
                "can_score": interview.status == "submitted",
                **context(interview.user_id, interview.scheduled_at),
            }
        )
    return {
        "queues": [
            {"name": label, "count": len(tasks[label]), "items": tasks[label]} for label in labels
        ]
    }


@router.get("/clients")
async def clients(
    actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)
):
    return listed(
        [
            dump(x, {"password_hash"})
            for x in db.scalars(select(User).where(User.id.in_(assigned_ids(db, actor))))
        ]
    )


@router.get("/clients/{user_id}")
async def client(
    user_id: str,
    actor: User = Depends(require_roles("advisor", "admin")),
    db: Session = Depends(get_db),
):
    if not can_access_user(db, actor, user_id):
        raise AppError("FORBIDDEN", "该客户未分配给当前顾问。", 403)
    user = db.get(User, user_id)
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在。", 404)
    return {
        "user": dump(user, {"password_hash"}),
        "profile": dump(db.get(UserProfile, user_id)) if db.get(UserProfile, user_id) else None,
        "timeline": {
            "resumes": [
                dump(x, {"original_file_key", "parsed_text"})
                for x in db.scalars(select(Resume).where(Resume.user_id == user_id))
            ],
            "facts": [
                dump(x) for x in db.scalars(select(ResumeFact).where(ResumeFact.user_id == user_id))
            ],
            "jobs": [
                dump(x, {"raw_jd"})
                for x in db.scalars(select(Job).where(Job.created_by == user_id))
            ],
            "matches": [dump(x) for x in db.scalars(select(Match).where(Match.user_id == user_id))],
            "resume_versions": [
                dump(x)
                for x in db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user_id))
            ],
            "applications": [
                dump(x)
                for x in db.scalars(select(Application).where(Application.user_id == user_id))
            ],
            "interviews": [
                dump(x) for x in db.scalars(select(Interview).where(Interview.user_id == user_id))
            ],
            "orders": [dump(x) for x in db.scalars(select(Order).where(Order.user_id == user_id))],
        },
    }


class AssignmentIn(BaseModel):
    user_id: str
    advisor_id: str


@router.post("/assignments", status_code=201)
async def assign(
    data: AssignmentIn, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    user = db.get(User, data.user_id)
    advisor = db.get(User, data.advisor_id)
    if not user or user.role != "user":
        raise AppError("INVALID_ASSIGNEE", "只能分配普通用户。", 422)
    if not advisor or advisor.role != "advisor":
        raise AppError("INVALID_ADVISOR", "只能分配顾问账号。", 422)
    existing = db.scalar(
        select(AdvisorAssignment).where(
            AdvisorAssignment.user_id == user.id,
            AdvisorAssignment.advisor_id == advisor.id,
            AdvisorAssignment.status == "active",
        )
    )
    if existing:
        return dump(existing)
    row = AdvisorAssignment(user_id=user.id, advisor_id=advisor.id)
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action="advisor_assignment.created",
            entity_type="advisor_assignment",
            entity_id=row.id,
            metadata_json={"user_id": user.id, "advisor_id": advisor.id},
        )
    )
    db.commit()
    return dump(row)


class ReviewIn(BaseModel):
    approved: bool
    note: str = ""


@router.post("/resume-versions/{version_id}/review")
async def review(
    version_id: str,
    data: ReviewIn,
    actor: User = Depends(require_roles("advisor", "admin")),
    db: Session = Depends(get_db),
):
    row = db.get(ResumeVersion, version_id)
    if not row or not can_access_user(db, actor, row.user_id):
        raise AppError("FORBIDDEN", "无权审核该简历。", 403)
    if data.approved and row.guard_status != "passed":
        raise AppError("FACT_GUARD_BLOCKED", "事实检查未通过，不能批准。", 409)
    if data.approved and row.review_status != "advisor_review":
        raise AppError("RESUME_NOT_SUBMITTED", "用户尚未提交该简历审核。", 409)
    row.review_status = "approved" if data.approved else "rejected"
    row.reviewed_by = actor.id
    row.reviewed_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action="resume_version.approved" if data.approved else "resume_version.rejected",
            entity_type="resume_version",
            entity_id=row.id,
            metadata_json={"note": data.note[:500]},
        )
    )
    db.commit()
    return dump(row)


class ScoreIn(BaseModel):
    scorecard: dict
    feedback: dict


@router.post("/interviews/{interview_id}/score")
async def score_interview(
    interview_id: str,
    data: ScoreIn,
    actor: User = Depends(require_roles("advisor", "admin")),
    db: Session = Depends(get_db),
):
    row = db.get(Interview, interview_id)
    if not row or not can_access_user(db, actor, row.user_id):
        raise AppError("FORBIDDEN", "无权评分该面试。", 403)
    if row.status != "submitted":
        raise AppError("INTERVIEW_NOT_SUBMITTED", "用户提交回答后才能评分。", 409)
    row.scorecard_json = data.scorecard
    row.feedback_json = data.feedback
    row.status = "scored"
    row.advisor_id = actor.id
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action="interview.scored",
            entity_type="interview",
            entity_id=row.id,
        )
    )
    db.commit()
    return dump(row)


@router.get("/reports/weekly/{user_id}")
async def advisor_report(
    user_id: str,
    actor: User = Depends(require_roles("advisor", "admin")),
    db: Session = Depends(get_db),
):
    if not can_access_user(db, actor, user_id):
        raise AppError("FORBIDDEN", "该客户未分配给当前顾问。", 403)
    return weekly_report(db, user_id)


admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


class PackageIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_-]{2,50}$")
    name: str = Field(min_length=1, max_length=100)
    price_cents: int = Field(ge=0)
    billing_period: Literal["once", "month", "year"] = "once"
    resume_quota: int = Field(default=0, ge=0)
    application_quota: int = Field(default=0, ge=0)
    interview_quota: int = Field(default=0, ge=0)
    features_json: list[str] = Field(default_factory=list, max_length=30)


class PackagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price_cents: int | None = Field(default=None, ge=0)
    billing_period: Literal["once", "month", "year"] | None = None
    resume_quota: int | None = Field(default=None, ge=0)
    application_quota: int | None = Field(default=None, ge=0)
    interview_quota: int | None = Field(default=None, ge=0)
    features_json: list[str] | None = Field(default=None, max_length=30)
    is_active: bool | None = None


@admin_router.get("/packages")
async def admin_packages(
    actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    return listed([dump(x) for x in db.scalars(select(Package)).all()])


@admin_router.post("/packages", status_code=201)
async def create_package(
    data: PackageIn, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    if db.scalar(select(Package.id).where(Package.code == data.code)):
        raise AppError("PACKAGE_CODE_EXISTS", "套餐代码已存在。", 409)
    row = Package(**data.model_dump())
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action="package.created",
            entity_type="package",
            entity_id=row.id,
        )
    )
    db.commit()
    return dump(row)


@admin_router.patch("/packages/{package_id}")
async def update_package(
    package_id: str,
    data: PackagePatch,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.get(Package, package_id)
    if not row:
        raise AppError("PACKAGE_NOT_FOUND", "套餐不存在。", 404)
    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise AppError("PACKAGE_UPDATE_EMPTY", "请至少修改一个套餐字段。", 422)
    for key, value in changes.items():
        setattr(row, key, value)
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action="package.updated",
            entity_type="package",
            entity_id=row.id,
            metadata_json={"fields": sorted(changes.keys())},
        )
    )
    db.commit()
    return dump(row)


@admin_router.delete("/packages/{package_id}", status_code=204)
async def disable_package(
    package_id: str, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    row = db.get(Package, package_id)
    if not row:
        raise AppError("PACKAGE_NOT_FOUND", "套餐不存在。", 404)
    row.is_active = False
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action="package.disabled",
            entity_type="package",
            entity_id=row.id,
        )
    )
    db.commit()


class QuotaGrantIn(BaseModel):
    user_id: str
    quota_type: str
    amount: int
    reason: str
    idempotency_key: str


@admin_router.post("/quotas/grant", status_code=201)
async def grant_quota(
    data: QuotaGrantIn, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    if data.quota_type not in {"match", "resume", "application", "interview"}:
        raise AppError("INVALID_QUOTA_TYPE", "额度类型无效。", 422)
    if data.amount == 0 or not data.reason.strip() or not data.idempotency_key.strip():
        raise AppError("INVALID_QUOTA_GRANT", "数量、原因和幂等键不能为空。", 422)
    if not db.get(User, data.user_id):
        raise AppError("USER_NOT_FOUND", "用户不存在。", 404)
    db.commit()
    row = change(
        db,
        user_id=data.user_id,
        quota_type=data.quota_type,
        delta=data.amount,
        reason=data.reason.strip(),
        idempotency_key=data.idempotency_key,
        reference_type="admin_grant",
        reference_id=actor.id,
        request_hash=request_fingerprint(
            {
                "operation": "admin.quota_grant",
                "actor_user_id": actor.id,
                "user_id": data.user_id,
                "quota_type": data.quota_type,
                "amount": data.amount,
                "reason": data.reason.strip(),
            }
        ),
    )
    if was_created(row):
        db.add(
            AuditLog(
                actor_user_id=actor.id,
                action="quota.grant",
                entity_type="quota_ledger",
                entity_id=row.id,
                metadata_json={
                    "user_id": data.user_id,
                    "quota_type": data.quota_type,
                    "amount": data.amount,
                    "reason": data.reason.strip(),
                    "replayed": False,
                },
            )
        )
        db.commit()
    return dump(row)


@admin_router.get("/quotas/ledger")
async def admin_quota_ledger(
    actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    rows = db.scalars(select(QuotaLedger).order_by(QuotaLedger.created_at.desc())).all()
    return listed([dump(row) for row in rows])


@admin_router.get("/accounts/deletion-requests")
async def deletion_requests(
    actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    rows = db.scalars(
        select(User)
        .where(User.role == "user", User.status == "deletion_requested")
        .order_by(User.updated_at)
    ).all()
    return listed([dump(row, {"password_hash"}) for row in rows])


@admin_router.get("/system/status")
async def system_status(
    actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    return {
        "providers": provider_status(),
        "maintenance": run_maintenance(db),
    }


@admin_router.post("/accounts/{user_id}/purge")
async def purge_account(
    user_id: str, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    user = db.get(User, user_id)
    if not user or user.status != "deletion_requested":
        raise AppError("ACCOUNT_NOT_READY_FOR_DELETION", "账号未申请删除。", 409)
    purge_user_data(
        db,
        user,
        LocalStorage(),
        audit_action="account.purged",
        actor_user_id=actor.id,
    )
    return {"status": "deleted"}
