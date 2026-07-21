export type User = {
  id: string
  email: string
  display_name: string
  role: 'user' | 'advisor' | 'admin'
  status: string
}

export type CoachResumeItem = {
  text: string
  source_fact_ids: string[]
  target_requirement_ids: string[]
  new_claims: string[]
}

export type CoachInterviewAnswer = {
  question: string
  answer: string
  source_fact_ids: string[]
  follow_ups: string[]
}

export type CoachResult = {
  job: {
    id: string
    title: string
    company_name: string
    city: string
    responsibilities: string[]
    must_have: string[]
    nice_to_have: string[]
    keywords: string[]
    work_conditions: string[]
    uncertain_fields: string[]
  }
  tailored_resume: {
    id: string
    title: string
    guard_status: string
    content: {
      headline: string
      sections: Array<{ name: string; items: CoachResumeItem[] }>
      excluded_gaps: string[]
    }
  }
  interview_guide: {
    questions: Array<{
      id: string
      category: string
      question: string
      why_asked: string
      rubric: string[]
      follow_ups: string[]
    }>
    self_introduction: {
      duration_seconds: number
      text: string
      source_fact_ids: string[]
    }
    project_answers: CoachInterviewAnswer[]
    common_answers: CoachInterviewAnswer[]
    preparation_plan: string[]
    risk_reminders: string[]
  }
  ocr_provider: string
  notices: string[]
}
