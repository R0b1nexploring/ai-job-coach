export type User = { id: string; email: string; display_name: string; role: 'user'|'advisor'|'admin'; status: string }
export type ListResponse<T> = { items: T[]; page: number; page_size: number; total: number }
export type MissingInformation = { fact_id: string; field: string; question: string }
export type Resume = { id: string; display_name: string; parse_status: string; facts_confirmed_at?: string; missing_information_json?: MissingInformation[] }
export type Job = { id: string; company_name: string; title: string; city: string; keywords_json: string[]; status: string; source_url: string; published_at?: string }
export type ExperienceEntry = {
  id: string
  kind: 'internship' | 'project'
  title: string
  organization: string
  role_title: string
  location: string
  start_date: string
  end_date: string
  summary: string
  bullets_json: string[]
  skills_json: string[]
  source: 'user_added' | 'original_resume' | 'template'
  is_template: boolean
  is_own: boolean
  linked_to_facts: boolean
  linked_fact_id?: string | null
}
export type CampusAnnouncement = {
  id: string
  company_name: string
  title: string
  cities_json: string[]
  jobs_json: string[]
  majors_json: string[]
  announcement_url: string
  apply_url: string
  apply_email: string
  apply_kind: 'email' | 'url' | 'none'
  expired: boolean
  expired_at?: string | null
  published_at?: string | null
  batch: string
  written_test: string
  jobs?: Job[]
}
export type Match = { id: string; resume_id: string; job_id: string; total_score: number; recommendation: string; dimension_scores_json: Record<string,number>; evidence_json: Array<Record<string,unknown>>; gaps_json: Array<Record<string,unknown>>; confirmations_json: string[]; ai_explanation_json: {summary:string} }
export type CapabilityTarget = { id: string; job_id: string; requirement: string; deliverable: string; acceptance_criteria_json: string[]; estimated_hours: number; severity: 'low'|'medium'|'high'; status: 'pending'|'in_progress'|'achieved'|'abandoned'; evidence_text: string }
