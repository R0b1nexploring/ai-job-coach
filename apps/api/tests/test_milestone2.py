from types import SimpleNamespace

import pytest
from conftest import register
from sqlalchemy.orm import sessionmaker

from app.errors import AppError
from app.models.entities import Application, Job, User
from app.services.fact_guard import guard_content
from app.services.quota_service import balance, change


def fact(fact_id: str, text: str, *, user_id: str = "user", status: str = "user_confirmed"):
    return SimpleNamespace(
        id=fact_id,
        user_id=user_id,
        verification_status=status,
        value_json={"text": text},
        organization="",
        role_title="",
        start_date="",
        end_date="",
        source_text=text,
    )


def target(target_id: str, deliverable: str, *, user_id: str = "user"):
    return SimpleNamespace(
        id=target_id,
        user_id=user_id,
        status="pending",
        deliverable=deliverable,
        acceptance_criteria_json=["产出物可以打开"],
    )


def test_fact_guard_blocks_new_metric():
    content = {
        "sections": [
            {"items": [{"text": "提升效率 30%", "source_fact_ids": ["f1"], "new_claims": []}]}
        ]
    }
    result = guard_content(content, [fact("f1", "完成机构设计")])
    assert result["status"] == "blocked"
    assert any("30%" in issue for issue in result["issues"])


def test_fact_guard_requires_traceability():
    result = guard_content(
        {"sections": [{"items": [{"text": "真实描述", "source_fact_ids": []}]}]},
        [],
    )
    assert result["status"] == "blocked"
    assert "缺少事实来源" in result["issues"]


def test_fact_guard_rejects_cross_item_claim_splicing():
    result = guard_content(
        {
            "sections": [
                {
                    "items": [
                        {
                            "text": "完成流程改造并提升效率 30%",
                            "source_fact_ids": ["fact-a"],
                        }
                    ]
                }
            ]
        },
        [fact("fact-a", "完成流程改造"), fact("fact-b", "提升效率 30%")],
    )
    assert result["status"] == "blocked"
    assert any("30%" in issue for issue in result["issues"])


def test_fact_guard_rejects_untraced_english_tool():
    result = guard_content(
        {
            "sections": [
                {"items": [{"text": "使用 Python 编写脚本", "source_fact_ids": ["fact-a"]}]}
            ]
        },
        [fact("fact-a", "完成自动化练习")],
    )
    assert result["status"] == "blocked"
    assert any("Python" in issue for issue in result["issues"])


def test_fact_guard_rejects_unsupported_chinese_role_and_claim():
    result = guard_content(
        {
            "sections": [
                {
                    "items": [
                        {
                            "text": "主导供应链优化",
                            "source_fact_ids": ["fact-a"],
                        }
                    ]
                }
            ]
        },
        [fact("fact-a", "参与机械机构设计")],
    )

    assert result["status"] == "blocked"
    assert any("主导" in issue for issue in result["issues"])
    assert any("中文主张与引用来源语义不一致" in issue for issue in result["issues"])


@pytest.mark.parametrize(
    "claim",
    [
        "参与机械机构设计量产",
        "参与机械机构设计并获奖",
        "掌握机械机构设计",
        "参与机械机构设计并获得专利",
    ],
)
def test_fact_guard_rejects_short_unsupported_claim_additions(claim):
    result = guard_content(
        {
            "sections": [
                {"items": [{"text": claim, "source_fact_ids": ["fact-a"]}]}
            ]
        },
        [fact("fact-a", "参与机械机构设计")],
    )

    assert result["status"] == "blocked"
    assert any("未经来源支持的中文主张" in issue for issue in result["issues"])


@pytest.mark.parametrize("claim", ["完成机械机构设计", "协助机械机构设计"])
def test_fact_guard_allows_neutral_rephrasing_without_new_claims(claim):
    result = guard_content(
        {
            "sections": [
                {"items": [{"text": claim, "source_fact_ids": ["fact-a"]}]}
            ]
        },
        [fact("fact-a", "参与机械机构设计")],
    )

    assert result["status"] == "passed"


def test_fact_guard_rejects_content_without_any_checkable_item():
    result = guard_content({"sections": []}, [fact("fact-a", "完成机构设计")])

    assert result["status"] == "blocked"
    assert "简历内容没有可校验条目" in result["issues"]


def test_fact_guard_modes_handle_unachieved_targets_explicitly():
    learning_target = target("target-1", "使用 Python 完成自动化脚本")
    content = {
        "content_version": 2,
        "sections": [
            {
                "items": [
                    {
                        "bullets": [
                            {
                                "text": "使用 Python 完成自动化脚本",
                                "source_fact_ids": [],
                                "source_target_ids": ["target-1"],
                                "achieved": False,
                            }
                        ]
                    }
                ]
            }
        ],
    }
    submittable = guard_content(content, [], [learning_target], mode="submittable")
    assert submittable["status"] == "blocked"
    assert "可投递简历不得引用未达成目标" in submittable["issues"]

    blueprint = guard_content(content, [], [learning_target], mode="target")
    assert blueprint["status"] == "passed"
    assert blueprint["unachieved_count"] == 1

    del content["sections"][0]["items"][0]["bullets"][0]["achieved"]
    missing_marker = guard_content(content, [], [learning_target], mode="target")
    assert missing_marker["status"] == "blocked"
    assert "未达成条目缺少 achieved 标记" in missing_marker["issues"]


def test_fact_guard_rejects_cross_user_fact_and_target_references():
    current_fact = fact("current-fact", "完成 CAD 设计")
    current_target = target("current-target", "完成 PLC 练习")
    result = guard_content(
        {
            "sections": [
                {
                    "items": [
                        {
                            "text": "使用 CAD 和 PLC 完成练习",
                            "source_fact_ids": ["foreign-fact"],
                            "source_target_ids": ["foreign-target"],
                            "achieved": False,
                        }
                    ]
                }
            ]
        },
        [current_fact],
        [current_target],
        mode="target",
    )
    assert result["status"] == "blocked"
    assert "引用了未确认或不属于当前用户的事实" in result["issues"]
    assert "引用了不属于当前用户或已经失效的学习目标" in result["issues"]


def test_resume_generation_request_does_not_expose_test_injection_switch(client):
    schema = client.get("/openapi.json").json()
    properties = schema["components"]["schemas"]["VersionIn"]["properties"]
    assert "inject_unverified" not in properties


def test_quota_deduction_and_idempotency(db):
    db.add(User(id="u", email="quota-u@example.test", password_hash="test"))
    db.flush()
    change(db, user_id="u", quota_type="resume", delta=2, reason="grant", idempotency_key="grant")
    change(db, user_id="u", quota_type="resume", delta=-1, reason="use", idempotency_key="same")
    change(db, user_id="u", quota_type="resume", delta=-1, reason="use", idempotency_key="same")
    assert balance(db, "u", "resume") == 1


def test_quota_idempotency_is_scoped_by_user_and_type(db):
    db.add_all(
        [
            User(id="user-a", email="quota-a@example.test", password_hash="test"),
            User(id="user-b", email="quota-b@example.test", password_hash="test"),
        ]
    )
    db.flush()
    first = change(
        db,
        user_id="user-a",
        quota_type="resume",
        delta=2,
        reason="grant",
        idempotency_key="shared-key",
    )
    second = change(
        db,
        user_id="user-b",
        quota_type="resume",
        delta=3,
        reason="grant",
        idempotency_key="shared-key",
    )
    third = change(
        db,
        user_id="user-a",
        quota_type="application",
        delta=4,
        reason="grant",
        idempotency_key="shared-key",
    )
    db.commit()
    assert len({first.id, second.id, third.id}) == 3
    assert balance(db, "user-a", "resume") == 2
    assert balance(db, "user-b", "resume") == 3
    assert balance(db, "user-a", "application") == 4


def test_quota_cannot_overdraw_when_two_sessions_observed_the_same_balance(db):
    user = User(id="quota-race", email="quota-race@example.test", password_hash="test")
    db.add(user)
    db.flush()
    change(
        db,
        user_id=user.id,
        quota_type="resume",
        delta=1,
        reason="grant",
        idempotency_key="race-grant",
    )
    db.commit()

    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    with Session() as first, Session() as second:
        assert balance(first, user.id, "resume") == 1
        assert balance(second, user.id, "resume") == 1
        change(
            first,
            user_id=user.id,
            quota_type="resume",
            delta=-1,
            reason="first use",
            idempotency_key="race-first",
        )
        first.commit()
        with pytest.raises(AppError) as raised:
            change(
                second,
                user_id=user.id,
                quota_type="resume",
                delta=-1,
                reason="second use",
                idempotency_key="race-second",
            )
        assert raised.value.code == "QUOTA_EXHAUSTED"
        second.rollback()

    db.expire_all()
    assert balance(db, user.id, "resume") == 0


def test_application_valid_and_invalid_transitions(client, db):
    user = register(client)
    job = Job(
        created_by=user["id"],
        company_name="示例",
        title="工程师",
        raw_jd="负责机械设计",
        content_hash="1",
    )
    db.add(job)
    db.flush()
    change(
        db,
        user_id=user["id"],
        quota_type="application",
        delta=2,
        reason="test",
        idempotency_key="grant-app",
    )
    db.commit()
    app = client.post("/api/applications", json={"job_id": job.id}).json()
    bad = client.patch(f"/api/applications/{app['id']}/status", json={"status": "offer"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    good = client.patch(
        f"/api/applications/{app['id']}/status", json={"status": "preparing_resume"}
    )
    assert good.status_code == 409
    assert good.json()["error"]["code"] == "APPLICATION_CONFIRMATION_REQUIRED"
    confirmed = client.post(f"/api/applications/{app['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "preparing_resume"
    assert confirmed.json()["user_confirmed_at"]
    events = client.get(f"/api/applications/{app['id']}/events").json()
    assert events["total"] == 2


def test_application_create_is_idempotent(client, db):
    user = register(client)
    job = Job(
        created_by=user["id"],
        company_name="示例",
        title="工程师",
        raw_jd="负责机械设计",
        content_hash="2",
    )
    db.add(job)
    db.flush()
    change(
        db,
        user_id=user["id"],
        quota_type="application",
        delta=2,
        reason="test",
        idempotency_key="grant-app-idempotent",
    )
    db.commit()
    headers = {"Idempotency-Key": "same-application-request"}
    first = client.post("/api/applications", headers=headers, json={"job_id": job.id})
    second = client.post("/api/applications", headers=headers, json={"job_id": job.id})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert db.query(Application).count() == 1
    assert balance(db, user["id"], "application") == 1
    different_job = Job(
        created_by=user["id"],
        company_name="另一家公司",
        title="另一岗位",
        raw_jd="负责另一项工作",
        content_hash="application-idempotency-other-job",
    )
    db.add(different_job)
    db.commit()
    reused = client.post(
        "/api/applications",
        headers=headers,
        json={"job_id": different_job.id},
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert db.query(Application).count() == 1
    assert balance(db, user["id"], "application") == 1
