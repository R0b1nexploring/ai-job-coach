import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Job, ListResponse, Match, Resume } from '../types'
import { Empty, ErrorState, Loading } from '../components/States'

export function Jobs() {
  const client = useQueryClient()
  const [raw, setRaw] = useState('')
  const [company, setCompany] = useState('')
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api<ListResponse<Job>>('/api/jobs') })
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: () => api<ListResponse<Resume>>('/api/resumes') })
  const create = useMutation({
    mutationFn: () => api<Job>('/api/jobs/import-text', { method: 'POST', body: JSON.stringify({ raw_jd: raw, company_name: company, title, city: '杭州' }) }),
    onSuccess: () => { setRaw(''); setMessage('岗位已结构化。'); client.invalidateQueries({ queryKey: ['jobs'] }) },
  })
  const match = useMutation({
    mutationFn: (jobId: string) => api<Match>('/api/matches', { method: 'POST', body: JSON.stringify({ job_id: jobId, resume_id: resumes.data?.items[0]?.id }) }),
    onSuccess: (data) => { setMessage(`匹配完成：${data.total_score} 分，${data.recommendation}`); client.invalidateQueries({ queryKey: ['matches'] }) },
  })
  return <><span className="badge">人工导入 · 不绕过平台限制</span><h1 className="mt-3 text-4xl font-black">岗位库</h1>
    <div className="mt-6 grid gap-6 lg:grid-cols-[.9fr_1.1fr]"><form className="card space-y-3" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><h2 className="text-xl font-bold">粘贴 JD</h2><input className="field" placeholder="公司名称" value={company} onChange={(event) => setCompany(event.target.value)} /><input className="field" placeholder="岗位名称" value={title} onChange={(event) => setTitle(event.target.value)} /><textarea className="field min-h-48" placeholder="粘贴完整岗位描述（至少 10 个字）" value={raw} onChange={(event) => setRaw(event.target.value)} /><button className="btn" disabled={raw.length < 10 || create.isPending}>导入并结构化</button>{(create.error || match.error) && <ErrorState error={create.error || match.error} />}</form>
      <div className="space-y-3">{message && <p className="rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}{jobs.data?.items.length ? jobs.data.items.map((job) => <article className="card" key={job.id}><div className="flex justify-between gap-3"><div><h2 className="font-bold">{job.company_name} · {job.title}</h2><p className="text-sm text-black/50">{job.city} · {job.keywords_json.join(' / ') || '待人工补充关键词'}</p></div><button className="btn-secondary" disabled={!resumes.data?.items[0]} onClick={() => match.mutate(job.id)}>生成匹配</button></div></article>) : <Empty title="还没有岗位，粘贴一个公开 JD。" />}</div>
    </div><Matches /></>
}

function Matches() {
  const query = useQuery({ queryKey: ['matches'], queryFn: () => api<ListResponse<Match>>('/api/matches') })
  if (!query.data?.items.length) return null
  return <section className="mt-8"><h2 className="text-2xl font-bold">最近匹配</h2><div className="mt-4 grid gap-4 md:grid-cols-3">{query.data.items.map((item) => <Link to={`/app/matches/${item.id}`} className="card hover:border-sage" key={item.id}><p className="text-4xl font-black">{item.total_score}</p><p className="badge mt-3">{item.recommendation}</p></Link>)}</div></section>
}

export function MatchDetail() {
  const { id } = useParams()
  const [version, setVersion] = useState<any>()
  const [message, setMessage] = useState('')
  const query = useQuery({ queryKey: ['match', id], queryFn: () => api<Match>(`/api/matches/${id}`) })
  const versions = useQuery({ queryKey: ['resume-versions'], queryFn: () => api<ListResponse<any>>('/api/resume-versions') })
  const currentVersion = version || versions.data?.items?.find((item: any) => item.base_resume_id === query.data?.resume_id && item.job_id === query.data?.job_id)
  const generate = useMutation({
    mutationFn: () => api<any>('/api/resume-versions', { method: 'POST', headers: { 'Idempotency-Key': `web-version-${id}` }, body: JSON.stringify({ base_resume_id: query.data?.resume_id, job_id: query.data?.job_id, match_id: id }) }),
    onSuccess: (data) => { setVersion(data); setMessage(data.guard_status === 'passed' ? '定制简历已生成，事实检查通过。' : '检测到未经确认的新事实，已拦截。') },
  })
  const submitReview = useMutation({ mutationFn: () => api<any>(`/api/resume-versions/${currentVersion.id}/submit-review`, { method: 'POST' }), onSuccess: (data) => { setVersion(data); setMessage('已提交顾问审核，通过后才能下载或加入投递。') } })
  const queue = useMutation({ mutationFn: () => api<any>('/api/applications', { method: 'POST', headers: { 'Idempotency-Key': `web-application-${id}` }, body: JSON.stringify({ job_id: query.data?.job_id, resume_version_id: currentVersion.id }) }), onSuccess: () => setMessage('已加入投递队列。') })
  if (query.isLoading) return <Loading text="正在加载报告…" />
  if (query.error) return <ErrorState error={query.error} />
  const data = query.data!
  return <><Link to="/app/jobs" className="text-sage">← 返回岗位</Link>{message && <p className="mt-4 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
    {(generate.error || submitReview.error || queue.error) && <div className="mt-4"><ErrorState error={generate.error || submitReview.error || queue.error} /></div>}
    <div className="mt-5 grid gap-5 lg:grid-cols-[.65fr_1.35fr]"><aside className="card bg-sage text-white"><p className="opacity-70">综合匹配</p><p className="mt-4 text-7xl font-black">{data.total_score}</p><h1 className="mt-2 text-2xl font-bold">{data.recommendation}</h1><p className="mt-5 text-sm opacity-80">{data.ai_explanation_json.summary}</p></aside><main className="space-y-5"><section className="card"><h2 className="font-bold">六项评分</h2><div className="mt-4 grid grid-cols-2 gap-3">{Object.entries(data.dimension_scores_json).map(([key, value]) => <div key={key} className="rounded-xl bg-cream p-3"><p className="text-xs text-black/50">{key}</p><b className="text-2xl">{value}</b></div>)}</div></section><section className="card"><h2 className="font-bold">能力缺口</h2>{data.gaps_json.length ? <ul className="mt-3 space-y-2">{data.gaps_json.map((gap: any, index) => <li key={index}>△ {gap.requirement}：{gap.action}</li>)}</ul> : <p className="mt-2 text-black/50">未发现明确缺口。</p>}</section><section className="card"><h2 className="font-bold">待确认项</h2><p className="mt-2">{data.confirmations_json.join('；') || '暂无'}</p></section><section className="card"><h2 className="font-bold">下一步</h2><div className="mt-4 flex flex-wrap gap-3">{!currentVersion && <button className="btn" onClick={() => generate.mutate()}>生成定制简历</button>}{currentVersion?.guard_status === 'passed' && ['draft', 'user_review', 'rejected'].includes(currentVersion.review_status) && <button className="btn" onClick={() => submitReview.mutate()}>提交顾问审核</button>}{currentVersion?.review_status === 'advisor_review' && <p className="rounded-xl bg-amber-50 px-4 py-2 text-amber-800">等待顾问审核</p>}{currentVersion?.review_status === 'approved' && <><a className="btn-secondary" href={`/api/resume-versions/${currentVersion.id}/preview`} target="_blank" rel="noreferrer">预览单页版</a><a className="btn-secondary" href={`/api/resume-versions/${currentVersion.id}/download?format=html`}>下载 HTML</a><a className="btn-secondary" href={`/api/resume-versions/${currentVersion.id}/download`}>下载 DOCX</a><button className="btn" onClick={() => queue.mutate()}>加入投递队列</button></>}</div></section></main></div>
  </>
}
