"""Derived revisions: immutable lineage, targeted updates, and no-op reuse."""

from conftest import register
from test_resume_generation_v3 import (
    _bullets,
    _grant_resume_quota,
    _import_job,
    process_created_bundle,
    setup_bundle,
)
from sqlalchemy import select

from app.models.entities import QuotaReservation, ResumeBundle, ResumeVersion


def _parent(client, db):
    user, resume, profile = setup_bundle(client, db)
    _created, parent = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "revision-parent",
    )
    assert parent["status"] in {"ready", "degraded"}, parent
    return user, resume, profile, parent


def _first_bullet(client, version_id):
    content = client.get(f"/api/resume-versions/{version_id}/studio").json()["content_json"]
    for row in _bullets(content):
        if row["bullet"].get("text"):
            return row["bullet"]["id"], row["bullet"]["text"]
    raise AssertionError("no bullet")


def _revision(client, bundle_id, payload, key):
    return client.post(
        f"/api/resume-bundles/{bundle_id}/revisions",
        headers={"Idempotency-Key": key},
        json=payload,
    )


def test_rephrase_derives_child_and_keeps_parent_frozen(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    bullet_id, original_text = _first_bullet(client, parent["versions"]["submittable"]["id"])
    payload = {
        "operation": "rephrase",
        "source_version_hashes": parent["source_version_hashes"],
        "source_state_hash": parent["source_state_hash"],
        "selected": {"kind": "submittable", "bullet_id": bullet_id},
    }
    created = _revision(client, parent["id"], payload, "rev-rephrase")
    assert created.status_code == 202, created.text
    child = created.json()
    assert child["id"] != parent["id"]
    assert child["parent_bundle_id"] == parent["id"]
    assert child["status"] == "queued"

    processed = client.post(f"/api/resume-bundles/{child['id']}/process").json()
    assert processed["status"] in {"ready", "degraded"}, processed
    assert processed["revision_operation"] == "rephrase"
    assert processed["change_summary"]

    child_content = client.get(
        f"/api/resume-versions/{processed['versions']['submittable']['id']}/studio"
    ).json()["content_json"]
    parent_content = client.get(
        f"/api/resume-versions/{parent['versions']['submittable']['id']}/studio"
    ).json()["content_json"]
    child_bullets = {row["bullet"]["id"]: row["bullet"] for row in _bullets(child_content)}
    parent_bullets = {row["bullet"]["id"]: row["bullet"] for row in _bullets(parent_content)}
    assert child_bullets[bullet_id]["text"] != original_text
    assert parent_bullets[bullet_id]["text"] == original_text
    # Every other bullet is inherited unchanged.
    for key, bullet in parent_bullets.items():
        if key != bullet_id:
            assert child_bullets[key] == bullet
    # The blueprint is copied byte-for-byte for a submittable-only rephrase.
    child_target = client.get(
        f"/api/resume-versions/{processed['versions']['target']['id']}/studio"
    ).json()["content_json"]
    parent_target = client.get(
        f"/api/resume-versions/{parent['versions']['target']['id']}/studio"
    ).json()["content_json"]
    assert child_target == parent_target


def test_revision_replay_is_idempotent_and_does_not_recharge(client, db):
    user, _resume, _profile, parent = _parent(client, db)
    bullet_id, _text = _first_bullet(client, parent["versions"]["submittable"]["id"])
    payload = {
        "operation": "rephrase",
        "source_version_hashes": parent["source_version_hashes"],
        "source_state_hash": parent["source_state_hash"],
        "selected": {"kind": "submittable", "bullet_id": bullet_id},
    }
    first = _revision(client, parent["id"], payload, "rev-replay")
    assert first.status_code == 202, first.text
    reservations_before = len(list(db.scalars(select(QuotaReservation))))
    replay = _revision(client, parent["id"], payload, "rev-replay")
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]
    assert len(list(db.scalars(select(QuotaReservation)))) == reservations_before


def test_revision_rejects_changed_source_and_locked_bullet(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    version_id = parent["versions"]["submittable"]["id"]
    bullet_id, _text = _first_bullet(client, version_id)
    conflict = _revision(
        client,
        parent["id"],
        {
            "operation": "rephrase",
            "source_version_hashes": {"submittable": "stale-hash", "target": "stale-hash"},
            "selected": {"kind": "submittable", "bullet_id": bullet_id},
        },
        "rev-conflict",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"

    locked = client.post(
        f"/api/resume-versions/{version_id}/lock",
        json={"bullet_id": bullet_id, "locked": True},
    )
    assert locked.status_code == 200, locked.text
    fresh = client.get(f"/api/resume-bundles/{parent['id']}").json()
    locked_revision = _revision(
        client,
        parent["id"],
        {
            "operation": "rephrase",
            "source_version_hashes": fresh["source_version_hashes"],
            "source_state_hash": fresh["source_state_hash"],
            "selected": {"kind": "submittable", "bullet_id": bullet_id},
        },
        "rev-locked",
    )
    assert locked_revision.status_code == 409
    assert locked_revision.json()["error"]["code"] == "RESUME_BULLET_LOCKED"


def test_revision_validates_operation_and_ownership(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    bad = _revision(
        client,
        parent["id"],
        {"operation": "explode", "selected": {"kind": "submittable", "bullet_id": "x"}},
        "rev-bad-op",
    )
    assert bad.status_code == 422

    other = register(client, email="intruder@example.test")
    assert other["id"]
    foreign = _revision(
        client,
        parent["id"],
        {"operation": "rephrase", "selected": {"kind": "submittable", "bullet_id": "x"}},
        "rev-foreign",
    )
    assert foreign.status_code == 404


def test_supplement_without_change_returns_existing_bundle(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    bullet_id, _text = _first_bullet(client, parent["versions"]["submittable"]["id"])
    noop = _revision(
        client,
        parent["id"],
        {
            "operation": "supplement",
            "source_version_hashes": parent["source_version_hashes"],
            "source_state_hash": parent["source_state_hash"],
            "selected": {"kind": "submittable", "bullet_id": bullet_id},
        },
        "rev-noop",
    )
    assert noop.status_code == 200, noop.text
    assert noop.json()["status"] == "unchanged"
    assert noop.json()["bundle"]["id"] == parent["id"]


def test_retarget_creates_independent_role_bundle(client, db):
    user, resume, _profile, parent = _parent(client, db)
    job = client.post(
        "/api/jobs/import-text",
        json={
            "company_name": "示例数据公司",
            "title": "数据分析实习生",
            "raw_jd": "负责使用 Python 清洗数据并输出分析报告。",
        },
    ).json()
    new_profile = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job["id"]]},
    ).json()
    _grant_resume_quota(db, user["id"], key="retarget-grant")
    created = _revision(
        client,
        parent["id"],
        {
            "operation": "retarget",
            "source_version_hashes": parent["source_version_hashes"],
            "source_state_hash": parent["source_state_hash"],
            "target_profile_id": new_profile["id"],
        },
        "rev-retarget",
    )
    assert created.status_code == 202, created.text
    child = created.json()
    assert child["parent_bundle_id"] == parent["id"]
    assert child["target_profile_id"] == new_profile["id"]
    processed = client.post(f"/api/resume-bundles/{child['id']}/process").json()
    assert processed["status"] in {"ready", "degraded"}, processed
    # The original role bundle and its versions remain readable and unchanged.
    assert client.get(f"/api/resume-bundles/{parent['id']}").json()["status"] in {
        "ready",
        "degraded",
    }
    parent_versions = list(
        db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == parent["id"]))
    )
    child_versions = list(
        db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == child["id"]))
    )
    assert {v.id for v in parent_versions}.isdisjoint({v.id for v in child_versions})
    stored_parent = db.get(ResumeBundle, parent["id"])
    assert stored_parent.target_profile_id != child["target_profile_id"]


def _child_versions(db, bundle_id):
    rows = list(db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == bundle_id)))
    return {row.kind: row for row in rows}


def test_local_lock_derives_child_without_quota_and_freezes_parent(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    bullet_id, _text = _first_bullet(client, parent["versions"]["submittable"]["id"])
    reservations_before = len(list(db.scalars(select(QuotaReservation))))
    derived = client.post(
        f"/api/resume-bundles/{parent['id']}/edits",
        json={"operation": "lock", "version_kind": "submittable", "bullet_id": bullet_id},
    )
    assert derived.status_code == 201, derived.text
    child = derived.json()
    assert child["parent_bundle_id"] == parent["id"]
    assert child["revision_operation"] == "lock"
    # Non-AI edit never charges generation quota.
    assert len(list(db.scalars(select(QuotaReservation)))) == reservations_before

    child_sub = _child_versions(db, child["id"])["submittable"]
    parent_sub = db.get(ResumeVersion, parent["versions"]["submittable"]["id"])
    child_bullet = next(
        row["bullet"] for row in _bullets(child_sub.content_json) if row["bullet"]["id"] == bullet_id
    )
    parent_bullet = next(
        row["bullet"] for row in _bullets(parent_sub.content_json) if row["bullet"]["id"] == bullet_id
    )
    assert child_bullet["locked"] is True
    assert parent_bullet["locked"] is not True
    # The child's guide is cloned and bound to the child version, no model call.
    child_guide = client.get(f"/api/interview-guides/{child['guides']['submittable']['id']}").json()
    assert child_guide["resume_version_id"] == child_sub.id
    assert child_guide["content_hash"] == child_sub.content_hash

    # The parent is now a historical baseline and rejects in-place edits.
    frozen = client.post(
        f"/api/resume-versions/{parent['versions']['submittable']['id']}/lock",
        json={"bullet_id": bullet_id, "locked": True},
    )
    assert frozen.status_code == 409
    assert frozen.json()["error"]["code"] == "VERSION_CONFLICT"


def test_local_content_edit_copies_the_other_version(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    detail = client.get(
        f"/api/resume-versions/{parent['versions']['submittable']['id']}/studio"
    ).json()
    content = detail["content_json"]
    original_headline = content.get("headline")
    content["headline"] = (original_headline or "目标岗位") + " · 定向调整"
    derived = client.post(
        f"/api/resume-bundles/{parent['id']}/edits",
        json={"operation": "content", "version_kind": "submittable", "content": content},
    )
    assert derived.status_code == 201, derived.text
    child = derived.json()
    child_versions = _child_versions(db, child["id"])
    parent_versions = _child_versions(db, parent["id"])
    assert child_versions["submittable"].content_json["headline"].endswith("· 定向调整")
    assert child_versions["target"].content_json == parent_versions["target"].content_json
    assert parent_versions["submittable"].content_json["headline"] == original_headline


def test_supplement_uses_provided_material_and_keeps_parent(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    bullet_id, original_text = _first_bullet(client, parent["versions"]["submittable"]["id"])
    material = client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": "补充的实践记录",
            "organization": "个人项目",
            "role_title": "成员",
            "summary": "补充了一次可验证的过程记录",
            "details_json": {"actions": "完成过程记录", "results": "产物可检查"},
        },
    ).json()
    created = _revision(
        client,
        parent["id"],
        {
            "operation": "supplement",
            "source_version_hashes": parent["source_version_hashes"],
            "source_state_hash": parent["source_state_hash"],
            "selected": {"kind": "submittable", "bullet_id": bullet_id},
            "material_ids": [material["id"]],
            "feedback": "补充这次过程记录",
        },
        "rev-supplement",
    )
    assert created.status_code == 202, created.text
    child = created.json()
    processed = client.post(f"/api/resume-bundles/{child['id']}/process").json()
    assert processed["status"] in {"ready", "degraded"}, processed
    child_sub = _child_versions(db, child["id"])["submittable"]
    parent_sub = db.get(ResumeVersion, parent["versions"]["submittable"]["id"])
    child_bullet = next(
        row["bullet"] for row in _bullets(child_sub.content_json) if row["bullet"]["id"] == bullet_id
    )
    parent_bullet = next(
        row["bullet"] for row in _bullets(parent_sub.content_json) if row["bullet"]["id"] == bullet_id
    )
    assert child_bullet["text"] != original_text
    assert parent_bullet["text"] == original_text


def test_supplement_updates_both_versions_when_facts_are_shared(client, db):
    _user, _resume, _profile, parent = _parent(client, db)
    parent_sub = db.get(ResumeVersion, parent["versions"]["submittable"]["id"])
    parent_tgt = db.get(ResumeVersion, parent["versions"]["target"]["id"])
    sub_bullet = next(
        row["bullet"]
        for row in _bullets(parent_sub.content_json)
        if row["bullet"].get("source_fact_ids")
    )
    shared = set(sub_bullet["source_fact_ids"])
    tgt_bullet = next(
        (
            row["bullet"]
            for row in _bullets(parent_tgt.content_json)
            if set(row["bullet"].get("source_fact_ids") or []) & shared
        ),
        None,
    )
    material = client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": "补充素材",
            "organization": "个人项目",
            "summary": "补充一次可验证的过程记录",
            "details_json": {"actions": "完成过程记录", "results": "产物可检查"},
        },
    ).json()
    created = _revision(
        client,
        parent["id"],
        {
            "operation": "supplement",
            "source_version_hashes": parent["source_version_hashes"],
            "source_state_hash": parent["source_state_hash"],
            "selected": {"kind": "submittable", "bullet_id": sub_bullet["id"]},
            "material_ids": [material["id"]],
            "feedback": "补充这次过程记录",
        },
        "rev-supplement-both",
    )
    assert created.status_code == 202, created.text
    child = created.json()
    processed = client.post(f"/api/resume-bundles/{child['id']}/process").json()
    assert processed["status"] in {"ready", "degraded"}, processed
    child_sub = db.get(ResumeVersion, processed["versions"]["submittable"]["id"])
    child_tgt = db.get(ResumeVersion, processed["versions"]["target"]["id"])
    child_sub_bullet = next(
        row["bullet"] for row in _bullets(child_sub.content_json) if row["bullet"]["id"] == sub_bullet["id"]
    )
    assert child_sub_bullet["text"] != sub_bullet["text"]
    if tgt_bullet is not None:
        child_tgt_bullet = next(
            row["bullet"] for row in _bullets(child_tgt.content_json) if row["bullet"]["id"] == tgt_bullet["id"]
        )
        assert child_tgt_bullet["text"] != tgt_bullet["text"]


def test_retarget_preserves_parent_locked_bullets(client, db):
    user, _resume, _profile, parent = _parent(client, db)
    sub_id = parent["versions"]["submittable"]["id"]
    bullet_id, bullet_text = _first_bullet(client, sub_id)
    locked = client.post(
        f"/api/resume-versions/{sub_id}/lock",
        json={"bullet_id": bullet_id, "locked": True},
    )
    assert locked.status_code == 200, locked.text
    job = client.post(
        "/api/jobs/import-text",
        json={
            "company_name": "示例数据公司",
            "title": "数据分析实习生",
            "raw_jd": "负责使用 Python 清洗数据并输出分析报告。",
        },
    ).json()
    new_profile = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job["id"]]},
    ).json()
    _grant_resume_quota(db, user["id"], key="retarget-locked-grant")
    fresh = client.get(f"/api/resume-bundles/{parent['id']}").json()
    created = _revision(
        client,
        parent["id"],
        {
            "operation": "retarget",
            "source_version_hashes": fresh["source_version_hashes"],
            "source_state_hash": fresh["source_state_hash"],
            "target_profile_id": new_profile["id"],
        },
        "rev-retarget-locked",
    )
    assert created.status_code == 202, created.text
    child = created.json()
    processed = client.post(f"/api/resume-bundles/{child['id']}/process").json()
    assert processed["status"] in {"ready", "degraded"}, processed
    child_sub = db.get(ResumeVersion, processed["versions"]["submittable"]["id"])
    matches = [
        row["bullet"]
        for row in _bullets(child_sub.content_json)
        if row["bullet"].get("locked")
    ]
    assert matches, "locked bullet must be preserved in the retarget child"
    assert matches[0]["id"] == bullet_id
    assert matches[0]["text"] == bullet_text
