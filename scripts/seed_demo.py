#!/usr/bin/env python3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.entities import (AdvisorAssignment, Application, ApplicationEvent, Interview, Job, Match, Notification, Package, QuotaLedger, Resume, ResumeFact, ResumeVersion, User, UserProfile)  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.providers.storage.local import LocalStorage  # noqa: E402


def seed():
    settings = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == settings.demo_user_email)):
            print("Demo data already exists; no changes made.")
            return
        admin = User(email=settings.demo_admin_email, password_hash=hash_password(settings.demo_admin_password), display_name="Demo 管理员", role="admin")
        advisor = User(email=settings.demo_advisor_email, password_hash=hash_password(settings.demo_advisor_password), display_name="王顾问", role="advisor")
        user = User(email=settings.demo_user_email, password_hash=hash_password(settings.demo_user_password), display_name="小陈", role="user")
        db.add_all([admin, advisor, user]); db.flush()
        db.add(UserProfile(user_id=user.id, school="示例理工大学", major="机械工程", graduation_year=2026, education_level="本科", target_cities_json=["杭州"], target_roles_json=["设备工程师", "机械助理工程师"], target_industries_json=["制造业", "生物医药"], accepts_shift=None, accepts_travel=True, accepts_factory=True, consented_at=datetime.now(timezone.utc)))
        db.add(AdvisorAssignment(user_id=user.id, advisor_id=advisor.id))
        packages = [
            Package(code="free", name="免费诊断", price_cents=0, billing_period="once", features_json=["1 次匹配报告"]),
            Package(code="basic", name="基础版", price_cents=29900, billing_period="7_days", resume_quota=5, features_json=["主简历重构", "5 个岗位版本"]),
            Package(code="job_member", name="求职会员", price_cents=69900, billing_period="month", resume_quota=20, application_quota=40, features_json=["岗位筛选", "周报"]),
            Package(code="interview_member", name="面试会员", price_cents=129900, billing_period="month", resume_quota=30, application_quota=60, interview_quota=2, features_json=["2 次人工模拟面试"]),
        ]
        db.add_all(packages); db.flush()
        sample_resume = ROOT / "data" / "samples" / "sample_resume.docx"
        file_key = LocalStorage().save(sample_resume.read_bytes(), ".docx")
        resume = Resume(user_id=user.id, original_file_key=file_key, original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", display_name="机械工程应届生示例简历.docx", parse_status="parsed", parsed_text="虚构样例：机械工程本科；毕业设计为红枣去核机机构设计；熟悉 CAD。", facts_confirmed_at=datetime.now(timezone.utc))
        db.add(resume); db.flush()
        facts = [
            ResumeFact(resume_id=resume.id, user_id=user.id, category="education", label="机械工程本科", value_json={"text": "示例理工大学机械工程本科，2026 年毕业"}, source_text="机械工程本科", verification_status="user_confirmed", created_by=user.id, confirmed_at=datetime.now(timezone.utc)),
            ResumeFact(resume_id=resume.id, user_id=user.id, category="projects", label="红枣去核机毕业设计", value_json={"text": "完成红枣去核机传动与执行机构设计，负责机构方案和 CAD 图纸"}, source_text="毕业设计", verification_status="user_confirmed", created_by=user.id, confirmed_at=datetime.now(timezone.utc)),
            ResumeFact(resume_id=resume.id, user_id=user.id, category="employment", label="客户需求跟进实习", value_json={"text": "实习中负责客户需求确认、问题跟踪与反馈整理"}, source_text="实习经历", verification_status="user_confirmed", created_by=user.id, confirmed_at=datetime.now(timezone.utc)),
        ]
        db.add_all(facts); db.flush()
        jd_defs = [
            ("示例制药设备有限公司", "设备工程师", "杭州", "负责设备点检、维护和 SOP 编制。要求机械相关本科，接受轮班，具备 CAD 基础。", ["设备点检", "SOP", "机械", "本科", "CAD"], ["可能轮班"]),
            ("虚构智能制造有限公司", "机械助理工程师", "杭州", "协助机械结构设计和图纸维护。机械本科，熟悉 CAD 或 SolidWorks。", ["机械", "本科", "CAD", "SolidWorks"], []),
            ("样例生物科技有限公司", "公用系统工程师", "杭州", "负责公用系统巡检、维护和跨部门协作。工程类本科，可接受工厂环境。", ["维护", "跨部门", "本科"], ["工厂环境"]),
        ]
        jobs = []
        for index, (company, title, city, jd, keywords, conditions) in enumerate(jd_defs):
            job = Job(created_by=user.id, company_name=company, title=title, city=city, raw_jd=jd, source_type="sample", source_url=f"https://example.test/jobs/{index+1}", responsibilities_json=[jd.split("。")[0]], must_have_json=["机械或工程相关本科"], nice_to_have_json=[], keywords_json=keywords, work_conditions_json=conditions, content_hash=f"sample-{index}", published_at=datetime.now(timezone.utc))
            db.add(job); jobs.append(job)
        db.flush()
        match = Match(user_id=user.id, resume_id=resume.id, job_id=jobs[0].id, total_score=68, recommendation="可以尝试", dimension_scores_json={"hard_requirements": 24, "skills": 10, "experience": 16, "keywords": 6, "preferences": 7, "freshness": 5}, evidence_json=[{"requirement": "机械相关本科", "status": "met", "fact_ids": [facts[0].id], "explanation": "专业与学历有已确认事实。"}], gaps_json=[{"requirement": "设备点检", "severity": "medium", "action": "完成设备点检表练习项目"}], confirmations_json=["是否接受轮班"], ai_explanation_json={"summary": "专业和学历匹配，但设备维护证据较弱。", "provider": "mock"})
        db.add(match)
        for quota, amount in [("resume", 20), ("application", 40), ("interview", 2)]:
            db.add(QuotaLedger(user_id=user.id, quota_type=quota, delta=amount, reason="MVP-1 种子演示额度", reference_type="seed", reference_id="demo-user", idempotency_key=f"seed:{user.id}:{quota}"))
        db.add(Notification(user_id=user.id, title="演示额度已发放", body="种子脚本已发放简历、投递和面试演示额度。在线支付尚未开放。"))
        version = ResumeVersion(user_id=user.id, base_resume_id=resume.id, job_id=jobs[0].id, title="示例制药设备有限公司 - 设备工程师", content_json={"headline": "机械工程应届生｜设备方向", "sections": [{"name": "项目经历", "items": [{"text": facts[1].value_json["text"], "source_fact_ids": [facts[1].id], "target_requirement_ids": [], "new_claims": []}]}], "excluded_gaps": ["设备点检"]}, traceability_json={"new_claims": []}, guard_status="passed", review_status="approved", reviewed_by=advisor.id, reviewed_at=datetime.now(timezone.utc))
        db.add(version); db.flush()
        statuses = ["pending_confirmation", "applied", "interview"]
        for index, status in enumerate(statuses):
            app = Application(user_id=user.id, job_id=jobs[index].id, resume_version_id=version.id if index == 0 else None, status=status, source_url=jobs[index].source_url, user_confirmed_at=datetime.now(timezone.utc) if index else None, applied_at=datetime.now(timezone.utc) if index else None)
            db.add(app); db.flush(); db.add(ApplicationEvent(application_id=app.id, from_status=None, to_status=status, actor_user_id=user.id, note="种子演示记录"))
        db.add(Interview(user_id=user.id, job_id=jobs[0].id, resume_version_id=version.id, status="submitted", question_set_json={"questions": [{"id": "q1", "category": "resume_verification", "question": "毕业设计中你负责了哪些计算？", "why_asked": "核实个人贡献", "rubric": ["说明职责", "给出依据"], "follow_ups": ["为什么采用该机构？"]}]}, answers_json={"q1": "待顾问评分"}, advisor_id=advisor.id))
        db.commit()
        print("Created complete fictional demo data.")


if __name__ == "__main__": seed()
