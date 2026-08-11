from copy import deepcopy
from types import SimpleNamespace

from app.providers.llm.schemas import InterviewStructuredOutput
from app.services.interview_generator import generate_questions, guard_interview_guide


def fact(**overrides):
    values = {
        "id": "fact-1",
        "verification_status": "user_confirmed",
        "category": "projects",
        "label": "设备巡检练习",
        "value_json": {"text": "使用 Python 完成设备巡检记录整理"},
        "organization": "示例制造公司",
        "role_title": "",
        "location": "",
        "start_date": "",
        "end_date": "",
        "source_text": "使用 Python 完成设备巡检记录整理",
        "provenance": "learned",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def target(**overrides):
    values = {
        "id": "target-1",
        "requirement": "掌握设备数据整理",
        "deliverable": "完成设备巡检记录整理练习",
        "status": "pending",
        "achieved_fact_id": None,
        "evidence_text": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def job():
    return SimpleNamespace(title="设备工程师")


def test_learned_answer_has_honesty_and_no_organization_packaging():
    learned = fact()
    guide = generate_questions(job(), facts=[learned], targets=[target()], unachieved_count=1)
    answer = guide["project_answers"][0]

    InterviewStructuredOutput.model_validate(guide)
    assert answer["provenance"] == "learned"
    assert answer["honesty_script"]
    assert "自主" in answer["structure"]["background"]
    assert learned.organization not in answer["structure"]["background"]
    assert answer["follow_ups"]
    assert any(item["risk"] == "high" for item in answer["follow_ups"])


def test_exposure_warning_matches_resume_version_count():
    learned = fact()
    guide = generate_questions(job(), facts=[learned], targets=[target()], unachieved_count=1)

    status, issues = guard_interview_guide(
        guide,
        [learned],
        [target()],
        expected_unachieved_count=1,
    )

    assert guide["exposure_warning"]["unachieved_count"] == 1
    assert status == "passed", issues


def test_guard_blocks_invented_number_per_project_answer():
    learned = fact()
    guide = generate_questions(job(), facts=[learned], unachieved_count=0)
    invented = deepcopy(guide)
    invented["project_answers"][0]["structure"]["result"] = "设备效率提升 30%"

    status, issues = guard_interview_guide(
        invented,
        [learned],
        expected_unachieved_count=0,
    )

    assert status == "blocked"
    assert any("30%" in issue for issue in issues)


def test_guard_rejects_wrong_exposure_count_and_missing_follow_up():
    original = fact(provenance="original_resume", organization="", id="fact-original")
    guide = generate_questions(job(), facts=[original], unachieved_count=2)
    guide["exposure_warning"]["unachieved_count"] = 1
    guide["project_answers"][0]["follow_ups"] = []

    status, issues = guard_interview_guide(
        guide,
        [original],
        expected_unachieved_count=2,
    )

    assert status == "blocked"
    assert any("条目数" in issue for issue in issues)
    assert any("缺少追问" in issue for issue in issues)
