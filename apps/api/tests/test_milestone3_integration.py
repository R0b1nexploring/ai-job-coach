from sqlalchemy import select

from app.models.entities import AdvisorAssignment, AuditLog, Package, User
from app.security import hash_password
from app.providers.payment.disabled import DisabledPaymentProvider
from app.errors import AppError
from conftest import docx_file, register


def add_packages(db):
    basic=Package(code="basic",name="基础版",price_cents=29900,billing_period="once",resume_quota=5)
    member=Package(code="member",name="求职会员",price_cents=69900,billing_period="month",resume_quota=20,application_quota=40,interview_quota=2)
    db.add_all([basic,member]);db.commit();return basic,member


def test_payment_provider_is_explicitly_disabled():
    import asyncio
    try:
        asyncio.run(DisabledPaymentProvider().create_payment(None))
    except AppError as exc:
        assert exc.code == "PAYMENT_NOT_AVAILABLE" and exc.status_code == 501
    else:
        raise AssertionError("Disabled Provider must not simulate payment")


def test_admin_grant_permission_audit_and_idempotency(client, db):
    user = register(client)
    denied = client.post("/api/admin/quotas/grant", json={"user_id":user["id"],"quota_type":"resume","amount":5,"reason":"演示","idempotency_key":"grant-once"})
    assert denied.status_code == 403
    admin=User(email="admin@example.test",password_hash=hash_password("Password123!"),display_name="管理员",role="admin");db.add(admin);db.commit()
    client.post("/api/auth/logout");client.post("/api/auth/login",json={"email":"admin@example.test","password":"Password123!"})
    body={"user_id":user["id"],"quota_type":"resume","amount":5,"reason":"MVP-1 演示额度","idempotency_key":"grant-once"}
    assert client.post("/api/admin/quotas/grant",json=body).status_code==201
    assert client.post("/api/admin/quotas/grant",json=body).status_code==201
    client.post("/api/auth/logout");client.post("/api/auth/login",json={"email":"a@example.test","password":"Password123!"})
    assert client.get("/api/quotas").json()["resume"] == 5
    assert db.scalar(select(AuditLog).where(AuditLog.action=="quota.grant")) is not None


def test_complete_registration_to_weekly_report_flow(client, db):
    user=register(client); add_packages(db)
    profile=client.put("/api/profile",json={"major":"机械工程","target_cities":["杭州"],"target_roles":["设备工程师"],"consent":True})
    assert profile.status_code==200
    resume=client.post("/api/resumes",files=docx_file()).json()
    facts=client.get(f"/api/resumes/{resume['id']}/facts").json()["items"]
    client.post(f"/api/resumes/{resume['id']}/confirm-facts")
    job=client.post("/api/jobs/import-text",json={"company_name":"虚构公司","title":"设备工程师","raw_jd":"负责设备点检、维护和 SOP。要求机械本科，熟悉 CAD。"}).json()
    match=client.post("/api/matches",json={"resume_id":resume["id"],"job_id":job["id"]}).json()
    admin=User(email="flow-admin@example.test",password_hash=hash_password("Password123!"),display_name="管理员",role="admin");db.add(admin);db.commit()
    client.post("/api/auth/logout");client.post("/api/auth/login",json={"email":"flow-admin@example.test","password":"Password123!"})
    for quota,amount in [("resume",5),("application",5),("interview",1)]:
        response=client.post("/api/admin/quotas/grant",json={"user_id":user["id"],"quota_type":quota,"amount":amount,"reason":"集成测试演示额度","idempotency_key":f"flow-{quota}"})
        assert response.status_code==201,response.text
    client.post("/api/auth/logout");client.post("/api/auth/login",json={"email":"a@example.test","password":"Password123!"})
    version=client.post("/api/resume-versions",headers={"Idempotency-Key":"integration-version"},json={"base_resume_id":resume["id"],"job_id":job["id"],"match_id":match["id"]})
    assert version.status_code==201,version.text
    version=version.json(); assert version["guard_status"]=="passed"
    assert client.post(f"/api/resume-versions/{version['id']}/approve").status_code == 404
    assert client.get(f"/api/resume-versions/{version['id']}/download").status_code==409
    unapproved_application = client.post("/api/applications",json={"job_id":job["id"],"resume_version_id":version["id"]})
    assert unapproved_application.status_code == 409 and unapproved_application.json()["error"]["code"] == "RESUME_NOT_APPROVED"
    assert client.post(f"/api/resume-versions/{version['id']}/submit-review").json()["review_status"] == "advisor_review"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/login",json={"email":"flow-admin@example.test","password":"Password123!"}).status_code == 200
    reviewed = client.post(f"/api/advisor/resume-versions/{version['id']}/review", json={"approved":True,"note":"集成测试审核"})
    assert reviewed.status_code == 200 and reviewed.json()["review_status"] == "approved"
    client.post("/api/auth/logout");client.post("/api/auth/login",json={"email":"a@example.test","password":"Password123!"})
    assert client.get(f"/api/resume-versions/{version['id']}/download").status_code==200
    preview = client.get(f"/api/resume-versions/{version['id']}/preview")
    assert preview.status_code == 200 and "text/html" in preview.headers["content-type"] and "size:A4" in preview.text
    assert preview.headers["cache-control"] == "private, no-store"
    html_download = client.get(f"/api/resume-versions/{version['id']}/download?format=html")
    assert html_download.status_code == 200 and "tailored-resume.html" in html_download.headers["content-disposition"]
    export_logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "resume_version.exported", AuditLog.entity_id == version["id"])))
    assert {row.metadata_json["format"] for row in export_logs} == {"docx", "html_preview", "html_download"}
    app=client.post("/api/applications",json={"job_id":job["id"],"resume_version_id":version["id"]}).json()
    for status in ["preparing_resume","ready_to_apply","applied"]: assert client.patch(f"/api/applications/{app['id']}/status",json={"status":status}).status_code==200
    interview=client.post("/api/interviews",json={"job_id":job["id"],"resume_version_id":version["id"]})
    assert interview.status_code==201 and interview.json()["question_set_json"]["questions"]
    report=client.get("/api/reports/weekly").json();assert report["applied"]==1 and report["new_jobs"]==1


def test_advisor_only_sees_assigned_clients(client, db):
    user_a=register(client); client.post('/api/auth/logout'); user_b=register(client,'b@example.test','B'); client.post('/api/auth/logout')
    advisor=User(email='advisor@example.test',password_hash=hash_password('Password123!'),display_name='顾问',role='advisor');db.add(advisor);db.flush();db.add(AdvisorAssignment(user_id=user_a['id'],advisor_id=advisor.id));db.commit()
    client.post('/api/auth/login',json={'email':'advisor@example.test','password':'Password123!'})
    clients=client.get('/api/advisor/clients').json()
    assert [x['id'] for x in clients['items']]==[user_a['id']]
    assert client.get(f"/api/advisor/clients/{user_b['id']}").status_code==403
