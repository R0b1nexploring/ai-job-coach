from typing import Literal

from pydantic import BaseModel, Field


class ResumeContactOutput(BaseModel):
    name: str = ""
    phone: str = ""
    email: str = ""
    city: str = ""


class ExtractedResumeFactOutput(BaseModel):
    category: str
    label: str
    organization: str = ""
    role_title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    text: str
    source_text: str


class ClarificationOutput(BaseModel):
    fact_index: int | None = None
    fact_id: str | None = None
    field: str
    question: str


class ResumeExtractionOutput(BaseModel):
    contact: ResumeContactOutput = Field(default_factory=ResumeContactOutput)
    facts: list[ExtractedResumeFactOutput] = Field(default_factory=list)
    missing_information: list[ClarificationOutput] = Field(default_factory=list)


class CapabilityTargetOutput(BaseModel):
    requirement: str
    category: str = "skills"
    severity: str = "medium"
    jd_evidence: str
    deliverable: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    estimated_hours: int = 0


class CapabilityPlanOutput(BaseModel):
    targets: list[CapabilityTargetOutput] = Field(default_factory=list)


class JobStructuredOutput(BaseModel):
    title: str
    company_name: str
    city: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    work_conditions: list[str] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)


class MatchExplanationOutput(BaseModel):
    summary: str
    evidence_links: list[dict] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    confirmations_needed: list[str] = Field(default_factory=list)


class RoleSuggestionOutput(BaseModel):
    role: str
    reason: str
    evidence_fact_ids: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)


class ResumeAnalysisOutput(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    role_suggestions: list[RoleSuggestionOutput] = Field(default_factory=list)
    missing_information: list[ClarificationOutput] = Field(default_factory=list)


class ResumeItemOutput(BaseModel):
    text: str
    source_fact_ids: list[str]
    target_requirement_ids: list[str] = Field(default_factory=list)
    new_claims: list[str] = Field(default_factory=list)


class ResumeSectionOutput(BaseModel):
    name: str
    items: list[ResumeItemOutput] = Field(default_factory=list)


class ResumeStructuredOutput(BaseModel):
    headline: str
    sections: list[ResumeSectionOutput] = Field(default_factory=list)
    excluded_gaps: list[str] = Field(default_factory=list)


class ResumeBulletV2Output(BaseModel):
    text: str = Field(description="不超过 45 个中文字符，并以输入允许的动作词开头")
    source_fact_ids: list[str] = Field(
        default_factory=list,
        description="已达成条目引用的 confirmed_facts id；不得编造 id",
    )
    source_target_ids: list[str] = Field(
        default_factory=list,
        description="未达成蓝图条目引用的 capability_targets id；不得编造 id",
    )
    achieved: bool = Field(description="引用 fact 时为 true；引用 capability target 时必须为 false")
    new_claims: list[str] = Field(
        default_factory=list,
        description="合规输出必须为空数组；如果无法避免新增主张，应省略该 bullet",
    )


class ResumeEntryV2Output(BaseModel):
    organization: str = ""
    role_title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[ResumeBulletV2Output] = Field(default_factory=list)


class ResumeSectionV2Output(BaseModel):
    name: str
    items: list[ResumeEntryV2Output] = Field(default_factory=list)


class ResumeStructuredV2Output(BaseModel):
    content_version: Literal[2] = 2
    kind: Literal["target", "submittable"]
    headline: str
    contact: ResumeContactOutput = Field(default_factory=ResumeContactOutput)
    sections: list[ResumeSectionV2Output] = Field(default_factory=list)
    excluded_gaps: list[str] = Field(default_factory=list)


ResumeContentOutput = ResumeStructuredOutput | ResumeStructuredV2Output


class InterviewQuestionOutput(BaseModel):
    id: str
    category: str
    question: str
    why_asked: str
    rubric: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)


class InterviewAnswerOutput(BaseModel):
    question: str
    answer: str
    source_fact_ids: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)


class InterviewFollowUpOutput(BaseModel):
    question: str
    how_to_answer: str
    risk: Literal["low", "medium", "high"] = "medium"


class InterviewAnswerStructureOutput(BaseModel):
    background: str
    my_role: str
    actions: list[str] = Field(default_factory=list)
    difficulties: str
    result: str
    verification: str


class InterviewProjectAnswerOutput(BaseModel):
    fact_id: str
    provenance: Literal["original_resume", "learned", "user_added"]
    question: str
    structure: InterviewAnswerStructureOutput
    follow_ups: list[InterviewFollowUpOutput] = Field(default_factory=list)
    honesty_script: str = ""


class InterviewExposureWarningOutput(BaseModel):
    unachieved_count: int = 0
    learned_count: int = 0
    message: str
    items: list[str] = Field(default_factory=list)


class SelfIntroductionOutput(BaseModel):
    duration_seconds: int = 90
    text: str
    source_fact_ids: list[str] = Field(default_factory=list)


class InterviewStructuredOutput(BaseModel):
    questions: list[InterviewQuestionOutput] = Field(default_factory=list)
    self_introduction: SelfIntroductionOutput
    exposure_warning: InterviewExposureWarningOutput
    project_answers: list[InterviewProjectAnswerOutput] = Field(default_factory=list)
    common_answers: list[InterviewAnswerOutput] = Field(default_factory=list)
    preparation_plan: list[str] = Field(default_factory=list)
    risk_reminders: list[str] = Field(default_factory=list)


class EmailMatchPointOutput(BaseModel):
    text: str
    source_fact_ids: list[str] = Field(default_factory=list)


class EmailDraftStructuredOutput(BaseModel):
    introduction: str
    match_points: list[EmailMatchPointOutput] = Field(default_factory=list, max_length=3)
    closing: str
