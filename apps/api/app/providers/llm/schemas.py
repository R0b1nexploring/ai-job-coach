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


class SelfIntroductionOutput(BaseModel):
    duration_seconds: int = 90
    text: str
    source_fact_ids: list[str] = Field(default_factory=list)


class InterviewStructuredOutput(BaseModel):
    questions: list[InterviewQuestionOutput] = Field(default_factory=list)
    self_introduction: SelfIntroductionOutput
    project_answers: list[InterviewAnswerOutput] = Field(default_factory=list)
    common_answers: list[InterviewAnswerOutput] = Field(default_factory=list)
    preparation_plan: list[str] = Field(default_factory=list)
    risk_reminders: list[str] = Field(default_factory=list)
