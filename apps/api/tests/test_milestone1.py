from datetime import datetime, timedelta, timezone

from app.models.entities import Job, ResumeFact, UserProfile
from app.services.job_normalizer import normalize_job
from app.services.matcher import score_match
from conftest import docx_file, register


def test_resume_upload_type_and_user_isolation(client):
    register(client)
    uploaded = client.post("/api/resumes", files=docx_file())
    assert uploaded.status_code == 201
    resume_id = uploaded.json()["id"]
    client.post("/api/auth/logout")
    register(client, "b@example.test", "用户B")
    response = client.get(f"/api/resumes/{resume_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESUME_NOT_FOUND"


def test_unsupported_resume_has_clear_error(client):
    register(client)
    response = client.post("/api/resumes", files={"file": ("resume.txt", b"hello", "text/plain")})
    assert response.status_code == 415
    assert "DOCX" in response.json()["error"]["message"]


def test_job_normalizer_is_deterministic():
    jd = "设备工程师\n负责设备点检和 SOP 编制\n要求机械相关本科，接受轮班，熟悉 CAD"
    assert normalize_job(jd, company_name="示例公司") == normalize_job(jd, company_name="示例公司")
    result = normalize_job(jd)
    assert "设备点检" in result["keywords"] and "轮班" in result["work_conditions"][0]


def test_matching_boundaries_and_hard_block(db):
    class Fact:
        id="f1"; verification_status="user_confirmed"; value_json={"text":"机械工程本科，使用 CAD 完成项目设计"}
    job = Job(created_by="u", company_name="c", title="t", raw_jd="x", keywords_json=["机械", "本科", "CAD"], work_conditions_json=["要求轮班"], content_hash="h", published_at=datetime.now(timezone.utc), status="active")
    profile = UserProfile(user_id="u", accepts_shift=False)
    result = score_match([Fact()], job, profile)
    assert result["hard_block"] is True
    assert result["recommendation"] in {"低优先", "不建议"}
    job.published_at = datetime.now(timezone.utc) - timedelta(days=45)
    assert score_match([Fact()], job, UserProfile(user_id="u", accepts_shift=True))["dimension_scores"]["freshness"] == 1


def test_matching_api_shows_dimensions_evidence_gaps_and_confirmations(client):
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    client.post(f"/api/resumes/{resume['id']}/confirm-facts")
    job = client.post("/api/jobs/import-text", json={"company_name":"示例公司","title":"设备工程师","raw_jd":"负责设备点检和 SOP 编制。要求机械相关本科，接受轮班，熟悉 CAD。"}).json()
    response = client.post("/api/matches", json={"resume_id":resume["id"],"job_id":job["id"]})
    assert response.status_code == 201, response.text
    data = response.json()
    assert len(data["dimension_scores_json"]) == 6
    assert isinstance(data["evidence_json"], list) and isinstance(data["gaps_json"], list)
    assert "是否接受轮班" in data["confirmations_json"]

