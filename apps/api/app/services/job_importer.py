import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CampusAnnouncement, Job, uid
from app.services.channel_importer import (
    ChannelImportError,
    _parse_datetime,
    import_channels,
    normalize_company_name,
    read_channel_rows,
)


FIELD_ALIASES = {
    "company_name": ("company_name", "company", "公司名称", "招聘公司", "公司"),
    "title": ("title", "announcement_title", "招聘公告", "公告名称", "name"),
    "cities": ("cities", "city", "工作城市", "招聘城市", "城市"),
    "jobs": ("jobs", "original_jobs", "招聘岗位", "岗位"),
    "majors": ("majors", "相关专业", "专业"),
    "announcement_url": ("announcement_url", "link", "公告链接", "详情链接"),
    "apply_url": ("apply_url", "from_url", "投递链接", "网申链接", "招聘链接"),
    "apply_email": ("apply_email", "email", "投递邮箱", "联系邮箱"),
    "published_at": ("published_at", "发布时间", "网申发布"),
    "expired_at": ("expired_at", "截止时间", "网申截止"),
    "class_years": ("class_years", "届数", "招聘对象"),
    "industries": ("industries", "公司标签", "行业"),
    "scale": ("scale", "公司规模", "规模"),
    "batch": ("batch", "批次", "招聘批次"),
    "written_test": ("written_test", "笔测情况", "有无笔试"),
    "company_description": ("company_description", "公司描述", "公司简介"),
    "notes": ("notes", "备注"),
    "source_updated_at": ("source_updated_at", "录入时间", "更新时间"),
}


class JobImportError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def read_campus_rows(path):
    return read_channel_rows(path)


def import_campus_announcements(
    db: Session,
    rows: list[dict],
    *,
    source: str,
    execute: bool = False,
    owner_user_id: str | None = None,
    created_by: str | None = None,
    column_map: dict[str, str] | None = None,
    resolver=None,
    default_source_updated_at: datetime | None = None,
) -> dict:
    stats = {
        "announcements_new": 0,
        "announcements_updated": 0,
        "jobs_new": 0,
        "jobs_updated": 0,
        "channels_new": 0,
        "channels_updated": 0,
        "skipped": 0,
        "rejected": 0,
        "channel_rejected": 0,
    }
    reasons: Counter[str] = Counter()
    channel_reasons: Counter[str] = Counter()
    seen_hashes: set[str] = set()
    for raw in rows:
        try:
            values = normalize_announcement_row(
                raw,
                source=source,
                owner_user_id=owner_user_id,
                column_map=column_map,
                default_source_updated_at=default_source_updated_at,
            )
        except JobImportError as exc:
            stats["rejected"] += 1
            reasons[exc.reason] += 1
            continue
        content_hash = values["content_hash"]
        if content_hash in seen_hashes:
            stats["skipped"] += 1
            continue
        seen_hashes.add(content_hash)
        channel_result = _import_apply_channel(
            db,
            values,
            source=source,
            execute=execute,
            owner_user_id=owner_user_id,
            resolver=resolver,
            default_source_updated_at=default_source_updated_at,
        )
        if channel_result.get("rejected"):
            stats["channel_rejected"] += 1
            channel_reasons[channel_result["reason"]] += 1
        elif channel_result.get("new"):
            stats["channels_new"] += 1
        elif channel_result.get("updated"):
            stats["channels_updated"] += 1
        values["channel_id"] = channel_result.get("channel_id")
        existing = db.scalar(
            select(CampusAnnouncement).where(CampusAnnouncement.content_hash == content_hash)
        )
        if existing:
            stats["announcements_updated"] += 1
            if execute:
                _update_announcement(existing, values)
                job_counts = _upsert_announcement_jobs(
                    db,
                    existing,
                    values,
                    created_by=created_by,
                )
                stats["jobs_new"] += job_counts["new"]
                stats["jobs_updated"] += job_counts["updated"]
            continue
        stats["announcements_new"] += 1
        if execute:
            row = CampusAnnouncement(
                id=uid(),
                owner_user_id=owner_user_id,
                created_by=created_by,
                **{
                    key: values[key]
                    for key in (
                        "company_name",
                        "company_name_normalized",
                        "title",
                        "cities_json",
                        "class_years_json",
                        "industry_tags_json",
                        "jobs_json",
                        "majors_json",
                        "announcement_url",
                        "apply_url",
                        "apply_email",
                        "scale",
                        "batch",
                        "written_test",
                        "company_description",
                        "published_at",
                        "expired_at",
                        "channel_id",
                        "source",
                        "source_updated_at",
                        "content_hash",
                        "notes",
                    )
                },
            )
            db.add(row)
            db.flush()
            job_counts = _upsert_announcement_jobs(
                db,
                row,
                values,
                created_by=created_by,
            )
            stats["jobs_new"] += job_counts["new"]
            stats["jobs_updated"] += job_counts["updated"]
    if execute:
        db.commit()
    return {
        **stats,
        "rejected_reasons": dict(sorted(reasons.items())),
        "channel_rejected_reasons": dict(sorted(channel_reasons.items())),
        "executed": execute,
    }


def normalize_announcement_row(
    raw: dict,
    *,
    source: str,
    owner_user_id: str | None = None,
    column_map: dict[str, str] | None = None,
    default_source_updated_at: datetime | None = None,
) -> dict:
    company_name = _value(raw, "company_name", column_map)
    company_key = normalize_company_name(company_name)
    if not company_key:
        raise JobImportError("company_required")
    title = _value(raw, "title", column_map) or f"{company_name}校园招聘"
    jobs = _split_jobs(_value(raw, "jobs", column_map))
    majors = _split_list(_value(raw, "majors", column_map))
    if not majors and jobs:
        majors = _split_list(_extract_majors_from_jobs_field(_value(raw, "jobs", column_map)))
    apply_url = _value(raw, "apply_url", column_map)
    apply_email = _value(raw, "apply_email", column_map)
    if apply_url and "@" in apply_url and "://" not in apply_url:
        apply_email = apply_email or apply_url
        apply_url = ""
    announcement_url = _value(raw, "announcement_url", column_map)
    if not jobs and not announcement_url and not apply_url and not apply_email:
        raise JobImportError("announcement_or_jobs_required")
    source_updated_at = _parse_optional_datetime(_value(raw, "source_updated_at", column_map))
    if source_updated_at is None:
        source_updated_at = default_source_updated_at
    identity = json.dumps(
        [
            owner_user_id or "global",
            company_key,
            title,
            announcement_url,
            apply_url,
            apply_email,
            jobs,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "company_name": company_name[:200],
        "company_name_normalized": company_key[:200],
        "title": title[:300],
        "cities_json": _split_list(_value(raw, "cities", column_map)),
        "class_years_json": _split_list(_value(raw, "class_years", column_map)),
        "industry_tags_json": _split_list(_value(raw, "industries", column_map)),
        "jobs_json": jobs,
        "majors_json": majors,
        "announcement_url": announcement_url[:1000],
        "apply_url": apply_url[:1000],
        "apply_email": apply_email[:320],
        "scale": _value(raw, "scale", column_map)[:50],
        "batch": _value(raw, "batch", column_map)[:50],
        "written_test": _value(raw, "written_test", column_map)[:50],
        "company_description": _value(raw, "company_description", column_map)[:5000],
        "published_at": _parse_optional_datetime(_value(raw, "published_at", column_map)),
        "expired_at": _parse_optional_datetime(_value(raw, "expired_at", column_map)),
        "source": source[:200],
        "source_updated_at": source_updated_at,
        "content_hash": hashlib.sha256(identity.encode()).hexdigest(),
        "notes": _value(raw, "notes", column_map)[:5000],
    }


def _value(raw: dict, name: str, column_map: dict[str, str] | None) -> str:
    if column_map and column_map.get(name):
        return str(raw.get(column_map[name]) or "").strip()
    lowered = {str(key).strip().casefold(): value for key, value in raw.items()}
    for alias in FIELD_ALIASES[name]:
        if alias.casefold() in lowered:
            return str(lowered[alias.casefold()] or "").strip()
    return ""


def _parse_optional_datetime(value: str):
    text = (value or "").strip()
    if not text or text in {"招满即止", "未知", "长期", "待定"}:
        return None
    try:
        return _parse_datetime(text)
    except ChannelImportError as exc:
        raise JobImportError("invalid_date") from exc


def _split_list(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            item.strip() for item in re.split(r"[,，、;；|\s]+", value or "") if item.strip()
        )
    )[:50]


def _split_jobs(value: str) -> list[str]:
    text = value.replace("\\\\", "\n")
    parts = re.split(r"[、,，;/；|\n]+", text)
    jobs = []
    for part in parts:
        cleaned = re.sub(r"^相关专业[:：].*$", "", part).strip()
        cleaned = re.sub(r"（.*?）", "", cleaned).strip()
        if cleaned and cleaned not in jobs and not cleaned.startswith("相关专业"):
            jobs.append(cleaned[:200])
    return jobs[:40]


def _extract_majors_from_jobs_field(value: str) -> str:
    match = re.search(r"相关专业[:：]\s*(.+)$", value.replace("\\\\", "\n"), re.MULTILINE)
    return match.group(1) if match else ""


def _import_apply_channel(
    db: Session,
    values: dict,
    *,
    source: str,
    execute: bool,
    owner_user_id: str | None,
    resolver,
    default_source_updated_at: datetime | None,
) -> dict:
    if values["apply_email"]:
        channel_type = "email"
        url = values["apply_url"]
        email = values["apply_email"]
    elif values["apply_url"]:
        channel_type = "career_page"
        url = values["apply_url"]
        email = ""
    else:
        return {}
    result = import_channels(
        db,
        [
            {
                "company_name": values["company_name"],
                "channel_type": channel_type,
                "url": url,
                "email": email,
                "scope": "campus",
                "regions": "、".join(values["cities_json"]),
                "industries": "、".join(values["industry_tags_json"]),
            }
        ],
        source=source,
        execute=execute,
        owner_user_id=owner_user_id,
        resolver=resolver,
        default_source_updated_at=default_source_updated_at,
    )
    if result["rejected"]:
        reason = next(iter(result.get("rejected_reasons") or {"channel_rejected": 1}))
        return {"rejected": True, "reason": reason}
    from app.models.entities import ApplicationChannel

    channel = None
    if execute:
        if email:
            channel = db.scalar(
                select(ApplicationChannel).where(
                    ApplicationChannel.company_name_normalized
                    == values["company_name_normalized"],
                    ApplicationChannel.channel_type == "email",
                    ApplicationChannel.email == email,
                    ApplicationChannel.owner_user_id == owner_user_id
                    if owner_user_id
                    else ApplicationChannel.owner_user_id.is_(None),
                )
            )
        else:
            channel = db.scalar(
                select(ApplicationChannel).where(
                    ApplicationChannel.company_name_normalized
                    == values["company_name_normalized"],
                    ApplicationChannel.channel_type == "career_page",
                    ApplicationChannel.url == url,
                    ApplicationChannel.owner_user_id == owner_user_id
                    if owner_user_id
                    else ApplicationChannel.owner_user_id.is_(None),
                )
            )
    return {
        "new": result["new"] > 0,
        "updated": result["updated"] > 0,
        "channel_id": channel.id if channel else None,
    }


def _update_announcement(row: CampusAnnouncement, values: dict) -> None:
    row.title = values["title"]
    row.cities_json = values["cities_json"]
    row.class_years_json = values["class_years_json"]
    row.industry_tags_json = values["industry_tags_json"]
    row.jobs_json = values["jobs_json"]
    row.majors_json = values["majors_json"]
    row.announcement_url = values["announcement_url"]
    row.apply_url = values["apply_url"]
    row.apply_email = values["apply_email"]
    row.scale = values["scale"]
    row.batch = values["batch"]
    row.written_test = values["written_test"]
    row.company_description = values["company_description"]
    row.published_at = values["published_at"]
    row.expired_at = values["expired_at"]
    row.channel_id = values["channel_id"]
    row.source = values["source"]
    row.source_updated_at = values["source_updated_at"]
    row.notes = values["notes"]


def _upsert_announcement_jobs(
    db: Session,
    announcement: CampusAnnouncement,
    values: dict,
    *,
    created_by: str | None,
) -> dict:
    titles = values["jobs_json"] or [values["title"] or "校园招聘岗位"]
    city = " / ".join(values["cities_json"])
    counts = {"new": 0, "updated": 0}
    if not created_by:
        return counts
    for title in titles:
        raw_jd = _catalog_job_text(values, title, city)
        digest = hashlib.sha256(raw_jd.strip().encode()).hexdigest()
        existing = db.scalar(
            select(Job).where(
                Job.announcement_id == announcement.id,
                Job.title == title,
                Job.owner_user_id.is_(None) if announcement.owner_user_id is None else Job.owner_user_id == announcement.owner_user_id,
            )
        )
        if existing:
            existing.raw_jd = raw_jd
            existing.city = city[:100]
            existing.source_url = values["announcement_url"] or values["apply_url"]
            existing.channel_id = values["channel_id"]
            existing.source_updated_at = values["source_updated_at"]
            existing.content_hash = digest
            existing.keywords_json = list(
                dict.fromkeys([*values["jobs_json"], *values["majors_json"], *values["industry_tags_json"]])
            )[:20]
            counts["updated"] += 1
            continue
        db.add(
            Job(
                created_by=created_by,
                owner_user_id=announcement.owner_user_id,
                company_name=values["company_name"],
                title=title[:200],
                city=city[:100],
                source_type="campus_import",
                source_url=(values["announcement_url"] or values["apply_url"])[:1000],
                raw_jd=raw_jd,
                keywords_json=list(
                    dict.fromkeys(
                        [*values["jobs_json"], *values["majors_json"], *values["industry_tags_json"]]
                    )
                )[:20],
                content_hash=digest,
                published_at=values["published_at"],
                channel_id=values["channel_id"],
                announcement_id=announcement.id,
                source_updated_at=values["source_updated_at"],
                status="expired" if _is_expired(values["expired_at"]) else "active",
            )
        )
        counts["new"] += 1
    return counts


def _catalog_job_text(values: dict, title: str, city: str) -> str:
    parts = [
        f"公司：{values['company_name']}",
        f"招聘公告：{values['title']}",
        f"岗位：{title}",
    ]
    if city:
        parts.append(f"工作城市：{city}")
    if values["majors_json"]:
        parts.append("相关专业：" + "、".join(values["majors_json"]))
    if values["class_years_json"]:
        parts.append("招聘对象：" + "、".join(values["class_years_json"]))
    if values["expired_at"]:
        parts.append(f"网申截止：{values['expired_at'].date().isoformat()}")
    else:
        parts.append("网申截止：招满即止")
    parts.append("完整职责与要求以官方公告链接为准，本条不编造岗位职责。")
    return "\n".join(parts)


def _is_expired(expired_at: datetime | None) -> bool:
    if expired_at is None:
        return False
    current = datetime.now(UTC)
    compare = expired_at if expired_at.tzinfo else expired_at.replace(tzinfo=UTC)
    return compare < current
