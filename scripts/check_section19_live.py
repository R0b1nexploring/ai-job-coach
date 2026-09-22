#!/usr/bin/env python3
"""Section 19 live acceptance: three material classes and two role JDs.

Runs against the real provider configured in .env. It never logs the API key,
a full prompt or a full resume. Full generated text is written to a private,
gitignored directory for human review; stdout carries only metadata.

Usage:
    apps/api/.venv/bin/python scripts/check_section19_live.py --acknowledge-cost
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

TMP = Path(tempfile.mkdtemp(prefix="section19-live-"))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP / 'live.db'}")
os.environ.setdefault("LOCAL_STORAGE_PATH", str(TMP / "uploads"))
os.environ.setdefault("STORAGE_PROVIDER", "local")
Path(os.environ["LOCAL_STORAGE_PATH"]).mkdir(parents=True, exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, make_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.quota_service import change  # noqa: E402

OUTPUT_DIR = ROOT / "tmp" / "section19-live"

DESIGN_JD = (
    "机械结构设计工程师：负责产品机械结构方案与详细设计，"
    "使用 SolidWorks 完成三维建模和装配体设计，输出工程图并做干涉检查。"
)
PROCESS_JD = (
    "机械工艺工程师：负责机加工艺路线与工序规划，编制工艺文件与作业指导书，"
    "分析加工节拍与成本，使用 CAD 输出工装夹具方案。"
)


def _register(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "display_name": "验收用户"},
    )
    response.raise_for_status()
    return response.json()


def _grant(user_id: str, amount: int) -> None:
    engine = make_engine(get_settings().resolved_database_url())
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    with Session() as db:
        change(
            db,
            user_id=user_id,
            quota_type="resume",
            delta=amount,
            reason="section19 live acceptance",
            idempotency_key=f"section19-live:{user_id}",
        )
        db.commit()
    engine.dispose()


def _import_job(client: TestClient, company: str, title: str, raw_jd: str) -> dict:
    response = client.post(
        "/api/jobs/import-text",
        json={"company_name": company, "title": title, "raw_jd": raw_jd},
    )
    response.raise_for_status()
    return response.json()


def _profile(client: TestClient, job_id: str) -> dict:
    response = client.post(
        "/api/target-profiles", json={"mode": "single_jd", "job_ids": [job_id]}
    )
    response.raise_for_status()
    return response.json()


def _confirm_material(client: TestClient, title: str, organization: str, summary: str, tools: str) -> None:
    material = client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": title,
            "organization": organization,
            "role_title": "项目成员",
            "summary": summary,
            "details_json": {
                "actions": summary,
                "tools": tools,
                "results": "输出可检查的交付物并完成评审",
                "ownership": "本人负责方案与记录",
            },
        },
    ).json()
    client.post(f"/api/experience/{material['id']}/confirm").raise_for_status()


def _draft_material(client: TestClient, title: str, summary: str) -> None:
    client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": title,
            "organization": "个人练习",
            "summary": summary,
            "details_json": {"actions": summary, "tools": "SolidWorks"},
        },
    ).raise_for_status()


def _run_bundle(client: TestClient, profile_id: str, key: str) -> dict:
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": key},
        json={"target_profile_id": profile_id},
    )
    created.raise_for_status()
    bundle = created.json()
    processed = client.post(f"/api/resume-bundles/{bundle['id']}/process")
    processed.raise_for_status()
    return processed.json()


def _record(client: TestClient, label: str, bundle: dict) -> dict:
    meta = bundle.get("generation_metadata_json") or {}
    versions = bundle.get("versions") or {}
    summary = {
        "label": label,
        "status": bundle.get("status"),
        "writer": meta.get("writer"),
        "reviewer": meta.get("reviewer"),
        "next_actions": [a.get("kind") for a in (meta.get("next_actions") or [])],
        "degraded": meta.get("degraded"),
        "versions": {kind: row.get("content_hash", "")[:12] for kind, row in versions.items()},
        "guides": {kind: row.get("status") for kind, row in (bundle.get("guides") or {}).items()},
    }
    details = {}
    for kind, row in versions.items():
        detail = client.get(f"/api/resume-versions/{row['id']}/studio").json()
        content = detail.get("content_json") or {}
        bullets = [
            bullet
            for section in content.get("sections") or []
            for item in section.get("items") or []
            for bullet in item.get("bullets") or []
        ]
        cited = sorted(
            {rid for bullet in bullets for rid in (bullet.get("requirement_ids") or [])}
        )
        details[kind] = {
            "bullet_count": len(bullets),
            "requirement_ids": cited,
            "achieved_false": sum(1 for b in bullets if b.get("achieved") is False),
            "headline": content.get("headline"),
        }
    guide_details = {}
    for kind, row in (bundle.get("guides") or {}).items():
        guide = client.get(f"/api/interview-guides/{row['id']}").json()
        cards = (guide.get("content_json") or {}).get("project_cards") or []
        guide_details[kind] = {
            "status": guide.get("status"),
            "project_cards": len(cards),
            "has_practice_plan": all(bool(c.get("practice_plan")) for c in cards) if cards else None,
            "has_purpose": all(bool(c.get("purpose")) for c in cards) if cards else None,
        }
    summary["version_detail"] = details
    summary["guide_detail"] = guide_details
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{label}.json").write_text(
        json.dumps({"summary": summary, "bundle": bundle}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _revision_rephrase(client: TestClient, bundle: dict, key: str) -> dict:
    version_id = bundle["versions"]["submittable"]["id"]
    detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
    bullet_id = next(
        bullet["id"]
        for section in detail["content_json"].get("sections") or []
        for item in section.get("items") or []
        for bullet in item.get("bullets") or []
        if bullet.get("text")
    )
    created = client.post(
        f"/api/resume-bundles/{bundle['id']}/revisions",
        headers={"Idempotency-Key": key},
        json={
            "operation": "rephrase",
            "source_version_hashes": bundle.get("source_version_hashes") or {},
            "source_state_hash": bundle.get("source_state_hash") or "",
            "selected": {"kind": "submittable", "bullet_id": bullet_id},
        },
    )
    created.raise_for_status()
    child = created.json()
    processed = client.post(f"/api/resume-bundles/{child['id']}/process")
    processed.raise_for_status()
    return processed.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acknowledge-cost", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="use the mock provider to validate wiring")
    parser.add_argument("--only", choices=["rich", "sparse", "blank"], help="run only one material class")
    args = parser.parse_args()
    settings = get_settings()
    if args.dry_run:
        os.environ["LLM_PROVIDER"] = "mock"
        get_settings.cache_clear()
        settings = get_settings()
    if settings.llm_provider != "compatible" and not args.dry_run:
        print("REFUSED: real provider is not configured; aborting without spending.")
        return 2
    if not args.acknowledge_cost and not args.dry_run:
        print("REFUSED: pass --acknowledge-cost to confirm paid model calls.")
        return 2

    engine = make_engine(settings.resolved_database_url())
    Base.metadata.create_all(engine)
    engine.dispose()

    client = TestClient(app)
    only = args.only
    results = []

    if only in (None, "rich"):
        user = _register(client, "section19-live@example.test")
        _grant(user["id"], 20)
        design_job = _import_job(client, "示例设计公司", "机械结构设计工程师", DESIGN_JD)
        process_job = _import_job(client, "示例工艺公司", "机械工艺工程师", PROCESS_JD)
        design_profile = _profile(client, design_job["id"])
        process_profile = _profile(client, process_job["id"])
        _confirm_material(
            client,
            "减速箱装配体设计",
            "虚构理工大学",
            "使用 SolidWorks 完成减速箱装配体建模，输出工程图并做干涉检查",
            "SolidWorks、CAD",
        )
        _confirm_material(
            client,
            "机加工艺课程项目",
            "虚构理工大学",
            "编制阶梯轴加工工艺路线并输出工艺文件",
            "CAD",
        )
        print("[rich 1/3] rich material x design JD ...", flush=True)
        rich_design = _run_bundle(client, design_profile["id"], "live-rich-design")
        results.append(_record(client, "rich_design", rich_design))
        print("[rich 2/3] rich material x process JD ...", flush=True)
        results.append(
            _record(client, "rich_process", _run_bundle(client, process_profile["id"], "live-rich-process"))
        )
        print("[rich 3/3] rephrase revision on rich design ...", flush=True)
        results.append(
            _record(client, "rich_design_rephrase", _revision_rephrase(client, rich_design, "live-rich-rephrase"))
        )

    if only in (None, "sparse"):
        # Sparse material: one unconfirmed draft is enough to start.
        print("[sparse] sparse material x design JD ...", flush=True)
        sparse_user = _register(client, "section19-sparse@example.test")
        _grant(sparse_user["id"], 10)
        _draft_material(client, "自学装配体练习", "使用 SolidWorks 完成一个装配体练习并导出工程图")
        sparse_job = _import_job(client, "示例设计公司", "机械结构设计工程师", DESIGN_JD)
        sparse_profile = _profile(client, sparse_job["id"])
        results.append(
            _record(client, "sparse_design", _run_bundle(client, sparse_profile["id"], "live-sparse-design"))
        )

    if only in (None, "blank"):
        # Blank material: a valid JD alone still yields a concrete draft and project.
        print("[blank] blank material x design JD ...", flush=True)
        blank_user = _register(client, "section19-blank@example.test")
        _grant(blank_user["id"], 10)
        blank_job = _import_job(client, "示例设计公司", "机械结构设计工程师", DESIGN_JD)
        blank_profile = _profile(client, blank_job["id"])
        results.append(
            _record(client, "blank_design", _run_bundle(client, blank_profile["id"], "live-blank-design"))
        )

    print("\n=== summary ===")
    for row in results:
        versions = row["version_detail"]
        print(
            f"{row['label']}: status={row['status']} writer={row['writer']} "
            f"reviewer={row['reviewer']} degraded={row['degraded']}"
        )
        for kind, detail in versions.items():
            print(
                f"   {kind}: bullets={detail['bullet_count']} "
                f"reqs={len(detail['requirement_ids'])} unachieved={detail['achieved_false']}"
            )
        for kind, guide in row["guide_detail"].items():
            print(f"   guide {kind}: {guide}")
        print(f"   next_actions={row['next_actions']}")
    print(f"\nfull outputs written to {OUTPUT_DIR} (private, gitignored)")
    print("LIVE_CHECK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
