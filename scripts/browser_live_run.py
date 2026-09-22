#!/usr/bin/env python3
"""Drive the real UI in a local Chromium against the live API + real provider.

Saves step-by-step screenshots under tmp/browser-live/ for review. Uses the
demo account created for this run; never logs a password or resume content.
"""

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB = os.environ.get("BROWSER_LIVE_WEB", "http://localhost:5173")
OUT = Path(__file__).resolve().parents[1] / "tmp" / "browser-live"
OUT.mkdir(parents=True, exist_ok=True)

EMAIL = os.environ.get("BROWSER_LIVE_EMAIL", "")
PASSWORD = os.environ.get("BROWSER_LIVE_PASSWORD", "")
if not EMAIL or not PASSWORD:
    raise SystemExit("Set BROWSER_LIVE_EMAIL and BROWSER_LIVE_PASSWORD for a local demo account.")
JD = (
    "AI 应用后端工程师（AI Agent 方向）\n"
    "岗位职责：负责公司 AI 游戏资产管理助手系统的后端设计与研发；"
    "接入大模型能力，实现资源自动分析、描述生成、标签分类与智能检索；"
    "基于 MCP 等实现自然语言查询、工具调用与智能任务处理；"
    "负责向量检索、RAG 等 AI 应用技术落地与系统稳定性维护。\n"
    "任职要求：熟悉 Python 与 FastAPI；掌握 PostgreSQL、Redis；"
    "了解 Prompt 设计、Embedding、RAG、向量检索；了解 MCP、LangChain、LangGraph；"
    "熟悉 Linux 与 Docker 部署。"
)


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"shot {name}", flush=True)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 950})
        page = context.new_page()
        page.goto(f"{WEB}/login", wait_until="networkidle")
        shot(page, "01-login")

        page.get_by_label("邮箱").fill(EMAIL)
        page.get_by_label("密码").fill(PASSWORD)
        page.get_by_role("button", name="登录").click()
        page.wait_for_url("**/app/**", timeout=30_000)
        page.goto(f"{WEB}/app/resume-studio", wait_until="networkidle")
        page.wait_for_timeout(1_500)
        if page.locator("textarea").count() == 0:
            # An account with existing bundles may open on a later step; the JD
            # box lives on the target step.
            page.get_by_role("button", name=re.compile("岗位")).first.click()
            page.wait_for_timeout(800)
        print(f"url={page.url}", flush=True)
        print(f"textareas={page.locator('textarea').count()} title={page.title()!r}", flush=True)
        if page.locator("textarea").count() == 0:
            (OUT / "debug-studio.html").write_text(page.content(), encoding="utf-8")
            print("NO_TEXTAREA; dumped debug-studio.html", flush=True)
        shot(page, "02-studio")

        page.get_by_placeholder(re.compile("粘贴职位描述")).fill(JD)
        shot(page, "03-jd-filled")
        page.get_by_role("button", name="生成我的简历").click()
        page.wait_for_selector("text=已保存岗位并开始生成", timeout=60_000)
        shot(page, "04-generating")
        print("generation queued; waiting for result ...", flush=True)

        # Real-model output can fail the provenance gate; the workspace offers a
        # retry. Try a few times before giving up so the demo can complete.
        for attempt in range(1, 5):
            try:
                page.wait_for_selector('[data-testid="a4-preview"]', timeout=600_000)
                break
            except Exception:
                retry = page.get_by_role("button", name="重试生成")
                if retry.count() == 0:
                    shot(page, f"05-failed-{attempt}")
                    raise
                print(f"attempt {attempt} failed; clicking retry", flush=True)
                shot(page, f"05-failed-{attempt}")
                retry.click()
                page.wait_for_timeout(3_000)
        page.wait_for_timeout(2_000)
        shot(page, "05-result-submittable")

        page.get_by_role("button", name="蓝图 Plus", exact=True).click()
        page.wait_for_timeout(2_000)
        shot(page, "06-result-target")

        page.get_by_role("button", name="求职版", exact=True).click()
        page.get_by_role("button", name="导出与指南").click()
        page.wait_for_timeout(1_000)
        shot(page, "07-export")

        record = {
            "status": "ok",
            "url": page.url,
            "screenshots": sorted(p.name for p in OUT.glob("*.png")),
            "headings": page.locator("h1, h2, h3").all_inner_texts()[:20],
            "has_submittable": page.get_by_role("button", name="求职版", exact=True).count() > 0,
            "has_target": page.get_by_role("button", name="蓝图 Plus", exact=True).count() > 0,
            "guide_links": [
                page.get_by_role("link").nth(i).inner_text()
                for i in range(page.get_by_role("link").count())
                if "指南" in (page.get_by_role("link").nth(i).inner_text() or "")
            ],
        }
        # Capture the download endpoints straight from the rendered links.
        links = page.get_by_role("link")
        hrefs = []
        for index in range(links.count()):
            href = links.nth(index).get_attribute("href")
            if href and "studio-download" in href:
                hrefs.append(href)
        for index, href in enumerate(hrefs):
            resp = page.request.get(f"{WEB}{href}")
            if resp.ok:
                suffix = href.split("format=")[-1]
                (OUT / f"download-{index}.{suffix}").write_bytes(resp.body())
                record.setdefault("downloads", []).append(f"download-{index}.{suffix}")
        (OUT / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)

        browser.close()
    print("BROWSER_LIVE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
