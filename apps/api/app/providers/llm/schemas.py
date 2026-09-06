from typing import Annotated, Literal

from pydantic import BaseModel, Field

GroundedJobText = Annotated[str, Field(min_length=1, max_length=5000)]


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
    title: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    city: str = Field(default="", max_length=100)
    responsibilities: list[GroundedJobText] = Field(default_factory=list, max_length=30)
    must_have: list[GroundedJobText] = Field(default_factory=list, max_length=30)
    nice_to_have: list[GroundedJobText] = Field(default_factory=list, max_length=30)
    keywords: list[GroundedJobText] = Field(default_factory=list, max_length=50)
    work_conditions: list[GroundedJobText] = Field(default_factory=list, max_length=30)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)


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
    text: str = Field(
        description=(
            "经历条目写成不超过 80 字的动作-任务-结果短句，并以允许的动作词开头；"
            "技能词条只写工具或技能名，不要加掌握/熟悉"
        )
    )
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
    presentation: Literal["items", "tags"] = "items"
    items: list[ResumeEntryV2Output] = Field(default_factory=list)


class ResumeStructuredV2Output(BaseModel):
    content_version: Literal[2] = 2
    kind: Literal["target", "submittable"]
    headline: str
    contact: ResumeContactOutput = Field(default_factory=ResumeContactOutput)
    sections: list[ResumeSectionV2Output] = Field(default_factory=list)
    excluded_gaps: list[str] = Field(default_factory=list)


class ResumeBulletV3Output(ResumeBulletV2Output):
    id: str = ""
    locked: bool = False
    requirement_ids: list[str] = Field(default_factory=list)
    new_claims: list[str] = Field(default_factory=list, description="允许补充主张，在此记录补充内容")
    verification_status: Literal["source_based", "ai_generated"] = "ai_generated"
    achieved: bool = Field(default=False, description="仅有事实支持时为 true；AI 补充和蓝图目标为 false")


class ResumeEntryV3Output(ResumeEntryV2Output):
    bullets: list[ResumeBulletV3Output] = Field(default_factory=list)


class ResumeSectionV3Output(ResumeSectionV2Output):
    items: list[ResumeEntryV3Output] = Field(default_factory=list)


class ResumeStructuredV3Output(ResumeStructuredV2Output):
    content_version: Literal[3] = 3
    factuality_policy: Literal["ai_expansion"] = "ai_expansion"
    sections: list[ResumeSectionV3Output] = Field(default_factory=list)


class ResumeBulletRewriteOutput(BaseModel):
    text: str
    source_fact_ids: list[str] = Field(default_factory=list)
    source_target_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    achieved: bool = False
    new_claims: list[str] = Field(default_factory=list)
    verification_status: Literal["source_based", "ai_generated"] = "ai_generated"


ResumeContentOutput = ResumeStructuredOutput | ResumeStructuredV2Output | ResumeStructuredV3Output


class QualityDimensionOutput(BaseModel):
    score: int = Field(default=60, ge=0, le=100)
    notes: list[str] = Field(default_factory=list)


class QualityCriticOutput(BaseModel):
    dimensions: dict[str, QualityDimensionOutput] = Field(default_factory=dict)
    summary: str = ""


class GuideCardOutput(BaseModel):
    bullet_id: str
    main_question: str = ""
    follow_ups: list[str] = Field(default_factory=list)
    six_part_story: dict[str, str] = Field(default_factory=dict)
    personal_boundary: str = ""
    verification: str = ""
    danger: str = ""
    exposure_questions: list[str] = Field(default_factory=list)
    honest_boundary: str = ""
    missing_evidence: str = ""
    future_answer: str = ""
    source_fact_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class InterviewGuideStructuredOutput(BaseModel):
    kind: Literal["submittable", "target"]
    cards: list[GuideCardOutput] = Field(default_factory=list)
    self_intro_60s: str = ""
    self_intro_90s: str = ""
    jd_questions: list[str] = Field(default_factory=list)
    motivation: str = ""
    questions_to_ask: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)


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
    source_fact_ids: list[str] = Field(
        default_factory=list,
        description="只能逐字使用输入 confirmed_facts 中存在的 id，不得编造 id",
    )
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
    fact_id: str = Field(description="必须逐字使用输入 project_fact_ids 中的一个 id")
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
    source_fact_ids: list[str] = Field(
        default_factory=list,
        description="只能逐字使用输入 confirmed_facts 中存在的 id，不得编造 id",
    )


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
