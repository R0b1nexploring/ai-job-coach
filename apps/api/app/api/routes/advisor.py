from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import can_access_user, current_user, require_roles
from app.errors import AppError
from app.models.entities import AdvisorAssignment, Application, AuditLog, Interview, Package, QuotaLedger, Resume, ResumeVersion, User
from app.providers.storage.local import LocalStorage
from app.services.quota_service import change
from app.services.report_service import weekly_report
from .common import dump, listed


router = APIRouter(prefix="/api/advisor", tags=["advisor"])


def assigned_ids(db, actor):
    if actor.role == "admin": return list(db.scalars(select(User.id).where(User.role == "user")))
    return list(db.scalars(select(AdvisorAssignment.user_id).where(AdvisorAssignment.advisor_id == actor.id, AdvisorAssignment.status == "active")))


@router.get("/queues")
async def queues(actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)):
    ids = assigned_ids(db, actor)
    labels = ["新线索", "待咨询", "待付款", "待核实", "待修改", "待投递", "有面试", "待复盘", "退款/争议"]
    tasks = {label: [] for label in labels}
    for version in db.scalars(select(ResumeVersion).where(ResumeVersion.user_id.in_(ids), ResumeVersion.review_status.in_(["advisor_review", "draft"]))):
        tasks["待核实" if version.guard_status == "blocked" else "待修改"].append({"id": version.id, "user_id": version.user_id, "type": "resume", "risk": "high" if version.guard_status == "blocked" else "medium", "next_action": "核查事实" if version.guard_status == "blocked" else "审核简历"})
    for app in db.scalars(select(Application).where(Application.user_id.in_(ids), Application.status.in_(["pending_confirmation", "ready_to_apply"]))): tasks["待投递"].append({"id": app.id, "user_id": app.user_id, "type": "application", "risk": "low", "next_action": "确认并投递"})
    for interview in db.scalars(select(Interview).where(Interview.user_id.in_(ids), Interview.status.in_(["draft", "submitted"]))): tasks["有面试" if interview.status == "draft" else "待复盘"].append({"id": interview.id, "user_id": interview.user_id, "type": "interview", "risk": "medium", "next_action": "生成训练" if interview.status == "draft" else "评分复盘"})
    return {"queues": [{"name": label, "count": len(tasks[label]), "items": tasks[label]} for label in labels]}


@router.get("/clients")
async def clients(actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)):
    return listed([dump(x, {"password_hash"}) for x in db.scalars(select(User).where(User.id.in_(assigned_ids(db, actor))))])


@router.get("/clients/{user_id}")
async def client(user_id: str, actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)):
    if not can_access_user(db, actor, user_id): raise AppError("FORBIDDEN", "该客户未分配给当前顾问。", 403)
    user = db.get(User, user_id)
    if not user: raise AppError("USER_NOT_FOUND", "用户不存在。", 404)
    return {"user": dump(user, {"password_hash"}), "timeline": {"applications": [dump(x) for x in db.scalars(select(Application).where(Application.user_id == user_id))], "interviews": [dump(x) for x in db.scalars(select(Interview).where(Interview.user_id == user_id))]}}


class AssignmentIn(BaseModel): user_id: str; advisor_id: str


@router.post("/assignments", status_code=201)
async def assign(data: AssignmentIn, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    row = AdvisorAssignment(user_id=data.user_id, advisor_id=data.advisor_id); db.add(row); db.commit(); return dump(row)


class ReviewIn(BaseModel): approved: bool; note: str = ""


@router.post("/resume-versions/{version_id}/review")
async def review(version_id: str, data: ReviewIn, actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)):
    row = db.get(ResumeVersion, version_id)
    if not row or not can_access_user(db, actor, row.user_id): raise AppError("FORBIDDEN", "无权审核该简历。", 403)
    if data.approved and row.guard_status != "passed": raise AppError("FACT_GUARD_BLOCKED", "事实检查未通过，不能批准。", 409)
    row.review_status = "approved" if data.approved else "rejected"; row.reviewed_by = actor.id; row.reviewed_at = datetime.now(timezone.utc); db.commit(); return dump(row)


class ScoreIn(BaseModel): scorecard: dict; feedback: dict


@router.post("/interviews/{interview_id}/score")
async def score_interview(interview_id: str, data: ScoreIn, actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)):
    row = db.get(Interview, interview_id)
    if not row or not can_access_user(db, actor, row.user_id): raise AppError("FORBIDDEN", "无权评分该面试。", 403)
    row.scorecard_json = data.scorecard; row.feedback_json = data.feedback; row.status = "scored"; row.advisor_id = actor.id; db.commit(); return dump(row)


@router.get("/reports/weekly/{user_id}")
async def advisor_report(user_id: str, actor: User = Depends(require_roles("advisor", "admin")), db: Session = Depends(get_db)):
    if not can_access_user(db, actor, user_id): raise AppError("FORBIDDEN", "该客户未分配给当前顾问。", 403)
    return weekly_report(db, user_id)


admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


class PackageIn(BaseModel):
    code: str; name: str; price_cents: int; billing_period: str = "once"; resume_quota: int = 0; application_quota: int = 0; interview_quota: int = 0; features_json: list = []


@admin_router.get("/packages")
async def admin_packages(actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)): return listed([dump(x) for x in db.scalars(select(Package)).all()])


@admin_router.post("/packages", status_code=201)
async def create_package(data: PackageIn, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    row = Package(**data.model_dump()); db.add(row); db.flush(); db.add(AuditLog(actor_user_id=actor.id, action="package.created", entity_type="package", entity_id=row.id)); db.commit(); return dump(row)


@admin_router.patch("/packages/{package_id}")
async def update_package(package_id: str, data: dict, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    row = db.get(Package, package_id)
    if not row: raise AppError("PACKAGE_NOT_FOUND", "套餐不存在。", 404)
    for key, value in data.items():
        if hasattr(row, key) and key not in {"id", "created_at"}: setattr(row, key, value)
    db.add(AuditLog(actor_user_id=actor.id, action="package.updated", entity_type="package", entity_id=row.id, metadata_json={"fields": sorted(data.keys())})); db.commit(); return dump(row)


@admin_router.delete("/packages/{package_id}", status_code=204)
async def disable_package(package_id: str, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    row = db.get(Package, package_id)
    if not row:
        raise AppError("PACKAGE_NOT_FOUND", "套餐不存在。", 404)
    row.is_active = False
    db.add(AuditLog(actor_user_id=actor.id, action="package.disabled", entity_type="package", entity_id=row.id))
    db.commit()


class QuotaGrantIn(BaseModel):
    user_id: str
    quota_type: str
    amount: int
    reason: str
    idempotency_key: str


@admin_router.post("/quotas/grant", status_code=201)
async def grant_quota(data: QuotaGrantIn, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    if data.quota_type not in {"match", "resume", "application", "interview"}:
        raise AppError("INVALID_QUOTA_TYPE", "额度类型无效。", 422)
    if data.amount == 0 or not data.reason.strip() or not data.idempotency_key.strip():
        raise AppError("INVALID_QUOTA_GRANT", "数量、原因和幂等键不能为空。", 422)
    if not db.get(User, data.user_id):
        raise AppError("USER_NOT_FOUND", "用户不存在。", 404)
    row = change(db, user_id=data.user_id, quota_type=data.quota_type, delta=data.amount, reason=data.reason.strip(), idempotency_key=data.idempotency_key, reference_type="admin_grant", reference_id=actor.id)
    db.add(AuditLog(actor_user_id=actor.id, action="quota.grant", entity_type="quota_ledger", entity_id=row.id, metadata_json={"user_id": data.user_id, "quota_type": data.quota_type, "amount": data.amount, "reason": data.reason.strip(), "idempotent": row.idempotency_key == data.idempotency_key}))
    db.commit()
    return dump(row)


@admin_router.get("/quotas/ledger")
async def admin_quota_ledger(actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(QuotaLedger).order_by(QuotaLedger.created_at.desc())).all()
    return listed([dump(row) for row in rows])


@admin_router.post("/accounts/{user_id}/purge")
async def purge_account(user_id: str, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.status != "deletion_requested": raise AppError("ACCOUNT_NOT_READY_FOR_DELETION", "账号未申请删除。", 409)
    storage = LocalStorage()
    for resume in db.scalars(select(Resume).where(Resume.user_id == user_id)):
        storage.delete(resume.original_file_key)
        resume.parsed_text = ""
        resume.deleted_at = datetime.now(timezone.utc)
    for version in db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user_id)):
        if version.export_file_key:
            storage.delete(version.export_file_key)
    user.status = "deleted"; user.deleted_at = datetime.now(timezone.utc); user.email = f"deleted-{user.id}@example.invalid"; user.display_name = "已删除用户"
    db.add(AuditLog(actor_user_id=actor.id, action="account.purged", entity_type="user", entity_id=user.id, metadata_json={"files_removed": True}))
    db.commit(); return {"status": "deleted"}
