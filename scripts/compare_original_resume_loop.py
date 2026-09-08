#!/usr/bin/env python3
"""Run the studio generate/export path against the original resume and score fidelity.

Does not print full resume text, contact numbers, or secrets.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_PDF = ROOT / "resume_pdf" / "resume_self" / "岑远轩.pdf"
ENV_PATH = ROOT / ".env"
RELOAD_PROBE = ROOT / "apps" / "api" / "app" / "config.py"
AUTH_PATH = Path.home() / ".grok" / "auth.json"
API = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")

ANCHORS = {
    "education": ["浙江科技大学", "机械制造", "中德"],
    "orgs": ["斯耐迪", "远丰石材", "浙江科技大学"],
    "skills": ["SolidWorks", "CET-6", "德语", "Python", "Excel"],
    "dates": ["2022.09", "2026.07", "2025.07", "2025.10", "2024.12"],
}

JD = """
公司：示例精密装备
岗位：注塑机技术支持工程师（应届）
城市：杭州
岗位职责：
- 为客户提供注塑机安装、调试与现场技术支持
- 根据图纸和现场反馈排查装配与工艺问题
- 使用 SolidWorks 查看和沟通零件/装配方案
- 整理技术文档并协助客户培训
任职要求：
- 机械制造、机械设计或自动化相关本科
- 熟悉 SolidWorks 或同类三维软件
- 能看懂机械图纸，了解装配与制造工艺
- 沟通清楚，可接受出差
加分项：德语或英语、生产实习、售后或技术支持经历
"""


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def original_text() -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(ORIGINAL_PDF), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout or ""


def score_against_original(generated_text: str, original: str) -> dict:
    orig = _norm(original)
    gen = _norm(generated_text)
    missing = []
    present = []
    for group, items in ANCHORS.items():
        for item in items:
            needle = _norm(item)
            if needle in gen:
                present.append(f"{group}:{item}")
            else:
                missing.append(f"{group}:{item}")
    total = len(present) + len(missing)
    recall = len(present) / total if total else 0
    education_first = False
    edu = gen.find(_norm("教育背景")) or gen.find(_norm("浙江科技大学"))
    intern = gen.find(_norm("斯耐迪"))
    if edu >= 0 and intern >= 0:
        education_first = edu < intern
    large_gap = recall < 0.75 or any(item.startswith("orgs:") for item in missing) or any(
        item.startswith("education:") for item in missing
    )
    return {
        "recall": round(recall, 3),
        "present": present,
        "missing": missing,
        "education_before_internship": education_first,
        "generated_chars": len(generated_text),
        "large_gap": large_gap,
    }


def grok_token() -> str:
    data = json.loads(AUTH_PATH.read_text())
    record = next(iter(data.values()))
    return str(record["key"])


def patch_env_for_grok(original: str) -> str:
    token = grok_token()
    lines = []
    mapping = {
        "LLM_API_BASE_URL": "https://api.x.ai/v1",
        "LLM_API_KEY": token,
        "LLM_MODEL": "grok-4-fast-non-reasoning",
        "LLM_MODEL_CHEAP": "grok-4-fast-non-reasoning",
        "LLM_MODEL_STRONG": "grok-4-fast-non-reasoning",
        "LLM_THINKING_ENABLED": "false",
    }
    seen = set()
    for line in original.splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.strip().startswith("#") else ""
        if key in mapping:
            lines.append(f"{key}={mapping[key]}")
            seen.add(key)
        else:
            lines.append(line)
    for key, value in mapping.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _worker_pids() -> list[int]:
    result = subprocess.run(["pgrep", "-f", "python -m app.worker"], capture_output=True, text=True)
    pids = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def pause_workers() -> list[int]:
    paused = []
    for pid in _worker_pids():
        try:
            os.kill(pid, signal.SIGSTOP)
            paused.append(pid)
        except OSError:
            continue
    return paused


def resume_workers(pids: list[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGCONT)
        except OSError:
            continue


def bump_reload() -> None:
    """uvicorn --reload watches Python files, not .env."""
    if RELOAD_PROBE.exists():
        now = time.time()
        os.utime(RELOAD_PROBE, (now, now))


def wait_health(timeout=90) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            response = httpx.get(f"{API}/api/health", timeout=5)
            last = response.text[:200]
            if response.status_code == 200:
                return
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(1.5)
    raise RuntimeError(f"API health check failed: {last}")


class StudioClient:
    def __init__(self):
        self.http = httpx.Client(
            base_url=API,
            timeout=httpx.Timeout(30.0, read=180.0),
            follow_redirects=True,
        )

    def register(self) -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        payload = {
            "email": f"loop-{stamp}@example.test",
            "password": "Password123!",
            "display_name": "对比用户",
        }
        response = self.http.post("/api/auth/register", json=payload)
        response.raise_for_status()
        return response.json()

    def admin_grant(self, user_id: str) -> None:
        login = self.http.post(
            "/api/auth/login",
            json={"email": "admin@example.test", "password": "ChangeMe123!"},
        )
        login.raise_for_status()
        grant = self.http.post(
            "/api/admin/quotas/grant",
            json={
                "user_id": user_id,
                "quota_type": "resume",
                "amount": 8,
                "reason": "原简历对比循环",
                "idempotency_key": f"loop-grant-{user_id[:8]}",
            },
        )
        grant.raise_for_status()

    def login_user(self, email: str) -> None:
        response = self.http.post("/api/auth/login", json={"email": email, "password": "Password123!"})
        response.raise_for_status()

    def upload_original(self) -> dict:
        with ORIGINAL_PDF.open("rb") as handle:
            response = self.http.post(
                "/api/resumes",
                files={"file": ("resume.pdf", handle, "application/pdf")},
                timeout=httpx.Timeout(30.0, read=300.0),
            )
        response.raise_for_status()
        resume = response.json()
        confirm = self.http.post(f"/api/resumes/{resume['id']}/confirm-facts")
        confirm_error = None
        if confirm.status_code >= 400:
            try:
                confirm_error = (confirm.json().get("error") or {}).get("code")
            except Exception:
                confirm_error = str(confirm.status_code)
            self._confirm_facts_individually(resume["id"])
        facts = self.http.get(f"/api/resumes/{resume['id']}/facts")
        facts.raise_for_status()
        seeded = self._seed_original_experience()
        return {
            "resume": resume,
            "facts": facts.json(),
            "confirm_error": confirm_error,
            "seeded_experience": seeded,
        }

    def _confirm_facts_individually(self, resume_id: str) -> None:
        facts = self.http.get(f"/api/resumes/{resume_id}/facts")
        if facts.status_code != 200:
            return
        items = facts.json().get("items") or []
        for item in items:
            fact_id = item.get("id")
            if not fact_id:
                continue
            self.http.post(f"/api/resume-facts/{fact_id}/confirm")

    def _seed_original_experience(self) -> int:
        rows = [
            {
                "kind": "education",
                "title": "机械制造及其自动化本科",
                "organization": "浙江科技大学",
                "role_title": "本科",
                "start_date": "2022-09",
                "end_date": "2026-07",
                "summary": "中德联合培养。机械核心课程与德语课程，德语 B2。",
            },
            {
                "kind": "internship",
                "title": "机械助理工程师实习",
                "organization": "佛山市南海斯耐迪精密机械有限公司",
                "role_title": "机械助理工程师",
                "start_date": "2025-07",
                "end_date": "2025-10",
                "summary": "分析生产线布局与设计方案，使用 SolidWorks 做零件和装配设计，减少装配冲突。",
            },
            {
                "kind": "internship",
                "title": "海外电商运营",
                "organization": "海外电商运营",
                "role_title": "运营",
                "start_date": "2024-07",
                "end_date": "2024-10",
                "summary": "分析销售数据、管理上架和订单，预测库存并提供售后支持。",
            },
            {
                "kind": "internship",
                "title": "车间工时统计",
                "organization": "远丰石材有限公司",
                "role_title": "数据统计",
                "start_date": "2023-07",
                "end_date": "2023-10",
                "summary": "出勤与工时统计，建立 Excel 汇总模板，支持人工成本核算。",
            },
            {
                "kind": "project",
                "title": "机械设计工作流数据库与后端开发",
                "organization": "课程项目",
                "role_title": "项目成员",
                "start_date": "2024-12",
                "end_date": "2025-03",
                "summary": "把机械设计规范资料结构化接入数据库，编写工作流标准化设计环节。",
            },
        ]
        created = 0
        for payload in rows:
            response = self.http.post("/api/experience", json=payload)
            if response.status_code >= 400:
                continue
            entry_id = response.json().get("id")
            if entry_id:
                self.http.post(f"/api/experience/{entry_id}/confirm")
                created += 1
        return created

    def create_profile(self) -> dict:
        job = self.http.post(
            "/api/jobs/import-text",
            json={"company_name": "示例精密装备", "title": "注塑机技术支持工程师", "raw_jd": JD, "city": "杭州"},
        )
        job.raise_for_status()
        profile = self.http.post(
            "/api/target-profiles",
            json={"mode": "single_jd", "job_ids": [job.json()["id"]]},
        )
        profile.raise_for_status()
        return {"job": job.json(), "profile": profile.json()}

    def generate(self, resume_id: str, profile_id: str) -> dict:
        created = self.http.post(
            "/api/resume-bundles",
            json={"base_resume_id": resume_id, "target_profile_id": profile_id},
            headers={"Idempotency-Key": f"loop-{resume_id[:8]}"},
            timeout=60,
        )
        created.raise_for_status()
        bundle_id = created.json()["id"]
        processed = self.http.post(
            f"/api/resume-bundles/{bundle_id}/process",
            timeout=httpx.Timeout(30.0, read=720.0),
        )
        processed.raise_for_status()
        return processed.json()

    def export(self, version_id: str, folder: Path, stem: str) -> dict:
        folder.mkdir(parents=True, exist_ok=True)
        studio = self.http.get(f"/api/resume-versions/{version_id}/studio")
        studio.raise_for_status()
        content = studio.json()["content_json"]
        (folder / f"{stem}.json").write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        paths = {}
        for fmt in ("html", "docx", "pdf"):
            response = self.http.get(
                f"/api/resume-versions/{version_id}/studio-download",
                params={"format": fmt},
                timeout=httpx.Timeout(30.0, read=180.0),
            )
            suffix = "html" if fmt == "html" else fmt
            dest = folder / f"{stem}.{suffix}"
            dest.write_bytes(response.content)
            paths[fmt] = str(dest.relative_to(ROOT))
            if response.status_code != 200:
                paths[f"{fmt}_status"] = response.status_code
        return {"content": content, "paths": paths, "quality": studio.json().get("quality_report_json") or {}}


def flatten_content(content: dict) -> str:
    parts = [
        str(content.get("headline") or ""),
        json.dumps(content.get("contact") or {}, ensure_ascii=False),
    ]
    for section in content.get("sections") or []:
        parts.append(str(section.get("name") or ""))
        for item in section.get("items") or []:
            parts.extend(
                str(item.get(key) or "")
                for key in ("organization", "role_title", "start_date", "end_date")
            )
            for bullet in item.get("bullets") or []:
                parts.append(str(bullet.get("text") or ""))
    return "\n".join(parts)


def fact_summary(facts_payload: dict) -> dict:
    items = facts_payload.get("items") or facts_payload.get("facts") or []
    if isinstance(facts_payload, list):
        items = facts_payload
    labels = []
    for item in items:
        label = item.get("label") or item.get("organization") or item.get("category") or ""
        if label:
            labels.append(str(label)[:40])
    return {"count": len(items), "labels": labels[:30]}


def run_round(out_dir: Path) -> dict:
    original = original_text()
    client = StudioClient()
    user = client.register()
    client.admin_grant(user["id"])
    client.login_user(user["email"])
    uploaded = client.upload_original()
    profile = client.create_profile()
    bundle = client.generate(uploaded["resume"]["id"], profile["profile"]["id"])
    report = {
        "bundle_status": bundle.get("status"),
        "writer": (bundle.get("generation_metadata_json") or {}).get("writer"),
        "degraded": (bundle.get("generation_metadata_json") or {}).get("degraded"),
        "repair_history": (bundle.get("generation_metadata_json") or {}).get("repair_history"),
        "facts": fact_summary(uploaded["facts"]),
        "confirm_error": uploaded.get("confirm_error"),
        "seeded_experience": uploaded.get("seeded_experience"),
        "versions": {},
    }
    for kind in ("submittable", "target"):
        version = (bundle.get("versions") or {}).get(kind) or {}
        version_id = version.get("id")
        if not version_id:
            continue
        exported = client.export(version_id, out_dir, kind)
        html = (out_dir / f"{kind}.html").read_text(encoding="utf-8", errors="ignore")
        fidelity = score_against_original(flatten_content(exported["content"]) + "\n" + html, original)
        report["versions"][kind] = {
            "paths": exported["paths"],
            "quality_status": (exported["quality"] or {}).get("status"),
            "fidelity": {key: fidelity[key] for key in ("recall", "missing", "education_before_internship", "large_gap")},
        }
    (out_dir / "compare.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "tmp" / "generated" / f"original-loop-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    original_env = ENV_PATH.read_text(encoding="utf-8")
    switched = False
    paused_workers: list[int] = []
    try:
        ENV_PATH.write_text(patch_env_for_grok(original_env), encoding="utf-8")
        switched = True
        paused_workers = pause_workers()
        bump_reload()
        print("switched LLM to xAI Grok; paused local worker so /process uses the API")
        time.sleep(8)
        wait_health()
        time.sleep(3)
        wait_health()
        report = run_round(out_dir)
        print(json.dumps({
            "out_dir": str(out_dir.relative_to(ROOT)),
            "bundle_status": report.get("bundle_status"),
            "writer": report.get("writer"),
            "facts_count": (report.get("facts") or {}).get("count"),
            "confirm_error": report.get("confirm_error"),
            "seeded_experience": report.get("seeded_experience"),
            "submittable": (report.get("versions") or {}).get("submittable", {}).get("fidelity"),
            "target": (report.get("versions") or {}).get("target", {}).get("fidelity"),
        }, ensure_ascii=False, indent=2))
        sub = ((report.get("versions") or {}).get("submittable") or {}).get("fidelity") or {}
        return 2 if sub.get("large_gap") else 0
    finally:
        resume_workers(paused_workers)
        if switched:
            ENV_PATH.write_text(original_env, encoding="utf-8")
            bump_reload()
            print("restored previous LLM provider and worker")


if __name__ == "__main__":
    raise SystemExit(main())
