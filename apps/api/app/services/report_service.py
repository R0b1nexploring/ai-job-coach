from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.models.entities import Application, Job, User


def weekly_report(db, user_id: str) -> dict:
    user = db.get(User, user_id)
    try:
        user_zone = ZoneInfo(user.timezone if user else "Asia/Shanghai")
    except Exception:
        user_zone = ZoneInfo("Asia/Shanghai")
    local_now = datetime.now(user_zone)
    local_start = datetime.combine(
        (local_now - timedelta(days=local_now.weekday())).date(), time.min, tzinfo=user_zone
    )
    start_utc = local_start.astimezone(timezone.utc)
    apps = list(
        db.scalars(
            select(Application).where(
                Application.user_id == user_id, Application.created_at >= start_utc
            )
        )
    )
    counts = {
        status: sum(a.status == status for a in apps)
        for status in ["applied", "contacted", "assessment", "interview", "offer", "rejected"]
    }
    new_jobs = (
        db.scalar(
            select(func.count(Job.id)).where(Job.created_by == user_id, Job.created_at >= start_utc)
        )
        or 0
    )
    has_data = bool(apps)
    applied_total = sum(
        counts[key]
        for key in ["applied", "contacted", "assessment", "interview", "offer", "rejected"]
    )
    conversion = {
        key: round(counts[key] / applied_total, 4) if applied_total else 0
        for key in ["contacted", "assessment", "interview", "offer", "rejected"]
    }
    return {
        "new_jobs": new_jobs,
        "user_confirmed": sum(a.user_confirmed_at is not None for a in apps),
        **counts,
        "conversion_rates": conversion,
        "period_start": start_utc.isoformat(),
        "blockers": [] if has_data else ["尚无投递或反馈记录"],
        "next_actions": ["补充投递结果", "确认本周目标岗位", "完善事实证据"]
        if has_data
        else ["导入目标岗位并创建首条投递记录"],
    }
