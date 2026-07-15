export type User = { id: string; email: string; display_name: string; role: 'user'|'advisor'|'admin'; status: string }
export type ListResponse<T> = { items: T[]; page: number; page_size: number; total: number }
export type Resume = { id: string; display_name: string; parse_status: string; facts_confirmed_at?: string }
export type Job = { id: string; company_name: string; title: string; city: string; keywords_json: string[]; status: string; source_url: string; published_at?: string }
export type Match = { id: string; resume_id: string; job_id: string; total_score: number; recommendation: string; dimension_scores_json: Record<string,number>; evidence_json: Array<Record<string,unknown>>; gaps_json: Array<Record<string,unknown>>; confirmations_json: string[]; ai_explanation_json: {summary:string} }
