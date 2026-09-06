#!/usr/bin/env python3
"""
完整工作流：目标画像 → 双轨简历生成 → 质量门禁 → 面试指南 → HTML/DOCX/PDF 导出。

直接运行（无需 API）：
  .venv/bin/python scripts/workflow_full.py

输出文件位于 output/ 目录。
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import os
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///./var/app.db")
os.environ.setdefault("LOCAL_STORAGE_PATH", "./var/uploads")
os.environ.setdefault("STORAGE_PROVIDER", "local")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("PAYMENT_PROVIDER", "disabled")
os.environ.setdefault("DEMO_USER_EMAIL", "user@example.test")
os.environ.setdefault("DEMO_USER_PASSWORD", "ChangeMe123!")

from app.config import get_settings
from app.database import make_engine, Base
from app.models.entities import (
    Resume, ResumeFact, ResumeVersion, ResumeBundle,
    Job, TargetProfile, TargetProfileSource,
    InterviewGuide, User, now, uid,
)
from app.security import hash_password
from app.services.target_profile_service import create_target_profile, dump_profile
from app.services.bundle_service import create_bundle, process_bundle, dump_bundle
from app.services.interview_guide_service import generate_guides_for_bundle, dump_guide
from app.services.html_resume_renderer import render_resume_html
from app.services.docx_resume_renderer import render_resume_docx
from app.services.pdf_export import export_pdf
from app.services.quota_service import change

# ── 演示数据 ──────────────────────────────────────────────────────────────
DEMO_JD = """
公司：海康机器人
岗位：嵌入式软件工程师（应届）
城市：杭州
学历要求：本科及以上，计算机、电子、自动化相关专业
岗位职责：
- 负责嵌入式 Linux 驱动开发与调试
- 参与 ARM 平台 BSP 移植与维护
- 编写技术文档与测试用例
硬性要求：
- 本科及以上学历，计算机/电子/自动化相关专业
- 熟悉 C/C++ 语言
- 了解 ARM 体系结构与嵌入式 Linux
加分项：
- 有 RTOS 或单片机项目经验
- 了解 I2C/SPI/UART 等总线协议
- 有 OpenCV 或 ROS 使用经验
关键词：嵌入式 Linux、ARM、C/C++、驱动开发、BSP
工作条件：标准工时，偶尔加班
"""

DEMO_RESUME = """
教育背景
2023.09 – 2027.06 ｜ 浙江工业大学 ｜ 自动化 ｜ 本科
主修课程：C 程序设计、嵌入式系统、自动控制原理、传感器技术

项目经历
2025.06 – 2025.09 ｜ 基于 STM32 的智能温控系统
- 使用 STM32F103 + DS18B20 实现温度采集与 PID 控制
- 编写 C 语言控制逻辑，控制精度 ±0.5°C
- 通过 OLED 实时显示温度曲线

2025.03 – 2025.05 ｜ 智能小车寻迹项目
- 基于 Arduino 平台，使用红外传感器实现循迹功能
- 参与 PID 速度闭环调试

技能
- C/C++：能独立完成嵌入式驱动开发
- 嵌入式 Linux：了解基本命令行与交叉编译
- 单片机：STM32、Arduino 开发经验
- 电路设计：Altium Designer 基础操作

语言
- 英语 CET-6
"""


async def main():
    settings = get_settings()
    engine = make_engine(settings.resolved_database_url())
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    out_dir = ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    with Session() as db:
        # ── 1. 创建用户 ──────────────────────────────────────────────────
        from sqlalchemy import select as sa_select
        user = db.scalar(sa_select(User).where(User.email == "workflow@example.test"))
        if not user:
            user = User(
                id=uid(), email="workflow@example.test",
                password_hash=hash_password("Test123!"),
                display_name="张明", role="user", status="active",
            )
            db.add(user)
            db.flush()
            print(f"✅ 创建用户：{user.display_name} ({user.email})")

        # ── 2. 发放演示额度 ──────────────────────────────────────────────
        for qt in ("resume", "match", "application", "interview"):
            change(db, user_id=user.id, quota_type=qt, delta=10,
                   reason="工作流演示额度",
                   idempotency_key=f"wf-demo-{user.id}-{qt}",
                   reference_type="seed", reference_id="workflow-demo")
        db.commit()
        print("✅ 已发放演示额度")

        # ── 3. 创建简历与事实 ────────────────────────────────────────────
        resume = db.scalar(
            sa_select(Resume).where(
                Resume.user_id == user.id, Resume.parse_status == "parsed")
        )
        if not resume:
            resume = Resume(
                id=uid(), user_id=user.id,
                original_file_key=f"uploads/{user.id}/resume.txt",
                original_media_type="text/plain",
                display_name="工作流演示简历", parse_status="parsed",
                parsed_text=DEMO_RESUME, parser_version="3.0",
            )
            db.add(resume)
            db.flush()
            # 按段落创建事实
            category_map = {"教育背景": "education", "项目经历": "projects",
                            "技能": "skills", "语言": "other"}
            section = "other"
            for block in DEMO_RESUME.strip().split("\n\n"):
                lines = block.strip().split("\n")
                header = lines[0].strip()
                if header in category_map:
                    section = category_map[header]
                    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
                else:
                    body = block
                if body.strip():
                    db.add(ResumeFact(
                        id=uid(), resume_id=resume.id, user_id=user.id,
                        created_by=user.id, category=section, label=header[:100],
                        value_json={"text": body.strip()},
                        source_text=body.strip()[:200],
                        verification_status="user_confirmed",
                        confirmed_at=datetime.now(timezone.utc),
                    ))
            db.flush()
            print(f"✅ 创建简历与事实库 ({resume.id})")

        # ── 4. 导入岗位 ───────────────────────────────────────────────────
        job = db.scalar(
            sa_select(Job).where(Job.created_by == user.id,
                                 Job.company_name == "海康机器人")
        )
        if not job:
            import hashlib
            job = Job(
                id=uid(), created_by=user.id,
                company_name="海康机器人", title="嵌入式软件工程师（应届）",
                city="杭州", source_type="manual", raw_jd=DEMO_JD.strip(),
                content_hash=hashlib.sha256(DEMO_JD.strip().encode()).hexdigest(),
                responsibilities_json=[
                    "负责嵌入式 Linux 驱动开发与调试",
                    "参与 ARM 平台 BSP 移植与维护",
                    "编写技术文档与测试用例"],
                must_have_json=[
                    "本科及以上学历，计算机/电子/自动化相关专业",
                    "熟悉 C/C++ 语言",
                    "了解 ARM 体系结构与嵌入式 Linux"],
                nice_to_have_json=[
                    "有 RTOS 或单片机项目经验",
                    "了解 I2C/SPI/UART 等总线协议",
                    "有 OpenCV 或 ROS 使用经验"],
                keywords_json=["嵌入式 Linux", "ARM", "C/C++", "驱动开发", "BSP"],
                work_conditions_json=["标准工时", "偶尔加班"],
                status="active",
            )
            db.add(job)
            db.flush()
            print(f"✅ 导入岗位：{job.title} @ {job.company_name}")

        # ── 5. 创建目标画像 ──────────────────────────────────────────────
        profile = await create_target_profile(db, user, mode="single_jd",
                                               job_ids=[job.id])
        db.commit()
        pd = dump_profile(profile)
        reqs = profile.snapshot_json.get("requirements", [])
        print(f"✅ 目标画像：{profile.title}")
        print(f"   聚合要求：{len(reqs)} 项")
        for r in reqs[:5]:
            print(f"   - [{r.get('priority','')}] {r.get('text','')[:60]}")

        # ── 6. 创建简历包 ─────────────────────────────────────────────────
        bundle = create_bundle(db, user, base_resume_id=resume.id,
                                target_profile_id=profile.id)
        db.commit()
        print(f"✅ 创建简历包（status={bundle.status}）")

        # ── 7. 生成双轨简历 + 质量门禁 ───────────────────────────────────
        result = await process_bundle(db, bundle.id)
        db.commit()
        bundle = db.get(ResumeBundle, bundle.id)
        print(f"✅ 简历包完成：status={bundle.status}")

        bd = dump_bundle(db, bundle)
        versions = {}
        for kind, info in bd.get("versions", {}).items():
            v = db.scalar(sa_select(ResumeVersion).where(ResumeVersion.id == info["id"]))
            versions[kind] = v
            print(f"   {'求职版' if kind == 'submittable' else '蓝图版'}: "
                  f"guard={info.get('status')}, quality={info.get('quality_status')}, "
                  f"未达成={info.get('unachieved_count')}")

        # ── 8. 获取画像关联岗位 ──────────────────────────────────────────
        sources = list(db.scalars(
            sa_select(TargetProfileSource).where(
                TargetProfileSource.target_profile_id == profile.id)))
        job_id = sources[0].job_id if sources else None
        job_title = profile.title

        # ── 9. 渲染输出 ──────────────────────────────────────────────────
        for kind, version in versions.items():
            if version is None:
                continue
            tag = "submittable" if kind == "submittable" else "target"
            content = version.content_json or {}
            snapshot = version.template_snapshot_json or {}
            title = f"{content.get('headline') or job_title} · {'求职版' if kind == 'submittable' else '蓝图版'}"

            # HTML
            html = render_resume_html(content, title, snapshot=snapshot)
            (out_dir / f"001-{tag}.html").write_text(html, encoding="utf-8")

            # DOCX
            docx_bytes = render_resume_docx(content, title, snapshot=snapshot)
            (out_dir / f"001-{tag}.docx").write_bytes(docx_bytes)

            # PDF
            try:
                pdf_bytes = await export_pdf(content, title, snapshot=snapshot)
                (out_dir / f"001-{tag}.pdf").write_bytes(pdf_bytes)
            except Exception as e:
                print(f"   ⚠️ PDF 导出跳过：{e}")

            print(f"   ✅ {tag}：HTML + DOCX + PDF 已导出")

        # ── 10. 生成面试指南 ─────────────────────────────────────────────
        guides = await generate_guides_for_bundle(db, bundle)
        db.commit()
        print(f"✅ 生成 {len(guides)} 份面试指南")

        for guide in guides:
            v = db.get(ResumeVersion, guide.resume_version_id)
            kind = v.kind if v else "unknown"
            tag = "submittable" if kind == "submittable" else "target"
            gd = dump_guide(guide)
            qs = gd.get("content_json", {}).get("questions", []) or gd.get("content_json", {}).get("sections", [])

            html = (
                "<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
                f"<title>面试指南 — {kind}</title>"
                "<style>body{font-family:sans-serif;max-width:800px;margin:2em auto;padding:0 1em;line-height:1.6}"
                "h2{border-bottom:2px solid #2F3E63;padding-bottom:4px;margin-top:2em;color:#1F2933}"
                ".qa{margin:1em 0;padding:1em;background:#f5f5f5;border-radius:6px;border-left:3px solid #2F3E63}"
                ".why{color:#666;font-size:.9em}.meta{color:#5B6575;font-size:.85em}</style></head><body>"
                f"<h1>面试指南 · {'求职版' if kind == 'submittable' else '蓝图版'}</h1>"
                f"<p class=meta><strong>目标岗位：</strong>{job_title}</p>"
                f"<p class=meta><strong>生成时间：</strong>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>"
                f"<p class=meta><strong>指南状态：</strong>{guide.status}</p><hr>"
            )

            for qa in qs:
                question = qa.get("question") or qa.get("title") or ""
                why = qa.get("why_asked") or qa.get("purpose") or ""
                rubrics = qa.get("rubric") or qa.get("guidelines") or qa.get("answers") or []
                followups = qa.get("follow_ups") or qa.get("followups") or []
                html += (
                    "<div class=qa>"
                    f"<p><strong>Q：</strong>{question}</p>"
                    + (f'<p class=why><strong>考察意图：</strong>{why}</p>' if why else "")
                    + "<p><strong>回答要点：</strong></p><ul>"
                    + "".join(f"<li>{r}</li>" for r in rubrics)
                    + "".join(f"<li><em>追问：</em>{f}</li>" for f in followups)
                    + "</ul></div>"
                )

            html += "</body></html>"
            (out_dir / f"001-interview-guide-{tag}.html").write_text(html, encoding="utf-8")
            print(f"   ✅ 面试指南：001-interview-guide-{tag}.html")

        # ── 11. 汇总 ─────────────────────────────────────────────────────
        print()
        print("=" * 60)
        print("  🎯 工作流完成")
        print("=" * 60)
        print(f"  用户：{user.display_name}")
        print(f"  岗位：{job.title} @ {job.company_name}")
        print(f"  画像：{profile.title}")
        print(f"  简历包状态：{bundle.status}")
        for kind, v in versions.items():
            if v:
                print(f"  {'求职版' if kind == 'submittable' else '蓝图版'}: "
                      f"{'✅ 通过' if v.guard_status == 'passed' else '⚠️ ' + v.guard_status}")
        print(f"  面试指南：{len(guides)} 份")
        print()
        print("  📁 输出文件：")
        for f in sorted(out_dir.glob("001-*")):
            sz = f.stat().st_size
            unit = "KB" if sz > 1024 else "B"
            val = sz / 1024 if sz > 1024 else sz
            print(f"     {f.name}  ({val:.1f} {unit})")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())