from sqlalchemy import select

from app.models.entities import ApplicationChannel, CampusAnnouncement, Job
from app.services.job_importer import import_campus_announcements
from conftest import register


def _row(**overrides):
    values = {
        "公司名称": "示例智造装备股份有限公司",
        "招聘公告": "2026 校园招聘简章",
        "工作城市": "杭州、长沙",
        "招聘岗位": "机械设计工程师、设备工程师",
        "相关专业": "机械类",
        "公告链接": "https://example.test/campus/smart-equip",
        "投递链接": "campus@example.com",
        "发布时间": "2026-08-01",
        "截止时间": "",
        "届数": "2026届",
        "公司标签": "智能制造",
        "批次": "秋招",
        "笔测情况": "有笔试",
        "公司描述": "虚构示例企业",
    }
    values.update(overrides)
    return values


def test_campus_import_is_idempotent_and_splits_jobs(db, client):
    user = register(client)
    first = import_campus_announcements(
        db,
        [_row()],
        source="demo_sample",
        execute=True,
        created_by=user["id"],
    )
    second = import_campus_announcements(
        db,
        [_row()],
        source="demo_sample",
        execute=True,
        created_by=user["id"],
    )

    assert first["announcements_new"] == 1
    assert first["jobs_new"] == 2
    assert first["channels_new"] == 1
    assert first["rejected"] == 0
    assert second["announcements_updated"] == 1
    assert second["announcements_new"] == 0
    assert db.scalar(select(CampusAnnouncement).where(True)) is not None
    assert len(list(db.scalars(select(CampusAnnouncement)))) == 1
    assert {job.title for job in db.scalars(select(Job)).all()} == {
        "机械设计工程师",
        "设备工程师",
    }
    channel = db.scalar(select(ApplicationChannel))
    assert channel.channel_type == "email"
    assert channel.email == "campus@example.com"


def test_unsafe_apply_url_rejects_channel_but_keeps_announcement(db, client):
    user = register(client)
    result = import_campus_announcements(
        db,
        [_row(投递链接="https://127.0.0.1/apply", **{"公告链接": ""})],
        source="security-test",
        execute=True,
        created_by=user["id"],
        resolver=lambda _host: ["127.0.0.1"],
    )

    assert result["announcements_new"] == 1
    assert result["channel_rejected"] == 1
    announcement = db.scalar(select(CampusAnnouncement))
    assert announcement is not None
    assert announcement.channel_id is None
    assert db.scalar(select(ApplicationChannel)) is None


def test_campus_board_is_shared_and_searchable(client, db):
    user = register(client)
    import_campus_announcements(
        db,
        [_row(), _row(公司名称="虚构生物工程有限公司", 招聘公告="春季校招", 工作城市="苏州")],
        source="demo_sample",
        execute=True,
        created_by=user["id"],
    )
    register(client, email="b@example.test", name="用户B")
    listed = client.get("/api/campus-announcements?q=智造")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["company_name"] == "示例智造装备股份有限公司"
    assert payload["items"][0]["apply_kind"] == "email"

    detail = client.get(f"/api/campus-announcements/{payload['items'][0]['id']}")
    assert detail.status_code == 200
    assert {job["title"] for job in detail.json()["jobs"]} == {
        "机械设计工程师",
        "设备工程师",
    }
