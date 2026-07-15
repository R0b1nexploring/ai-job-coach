import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ListResponse, Resume } from '../types'
import { Empty, ErrorState, Loading } from '../components/States'
import { factStatusLabels, guardStatusLabels, parseStatusLabels, reviewStatusLabels } from '../app/labels'

export function Resumes() {
  const client = useQueryClient()
  const [message, setMessage] = useState('')
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: () => api<ListResponse<Resume>>('/api/resumes') })
  const versions = useQuery({ queryKey: ['resume-versions'], queryFn: () => api<any>('/api/resume-versions') })
  const upload = useMutation({
    mutationFn: async (file: File) => { const body = new FormData(); body.append('file', file); return api('/api/resumes', { method: 'POST', body }) },
    onSuccess: () => { setMessage('简历已解析，请核对并确认事实库。'); client.invalidateQueries({ queryKey: ['resumes'] }) },
  })
  if (resumes.isLoading || versions.isLoading) return <Loading />
  return <><div className="flex flex-wrap items-end justify-between gap-4"><div><span className="badge">事实优先</span><h1 className="mt-3 text-4xl font-black">简历与事实库</h1></div><label className="btn cursor-pointer">上传 DOCX / PDF<input className="hidden" type="file" accept=".docx,.pdf" onChange={(event) => event.target.files?.[0] && upload.mutate(event.target.files[0])} /></label></div>
    {(upload.error || resumes.error || versions.error) && <div className="mt-5"><ErrorState error={upload.error || resumes.error || versions.error} /></div>}{message && <p className="mt-5 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
    <div className="mt-6 space-y-4">{resumes.data?.items.length ? resumes.data.items.map((resume) => <ResumeCard key={resume.id} resume={resume} />) : <Empty title="还没有简历，上传一份开始分析。" />}</div>
    <section className="mt-10"><h2 className="text-2xl font-bold">定制版本</h2><div className="mt-4 space-y-3">{versions.data?.items?.length ? versions.data.items.map((version: any) => <article className="card flex flex-wrap items-center justify-between gap-3" key={version.id}><div><b>{version.title}</b><p className="text-sm text-black/50">事实检查：{guardStatusLabels[version.guard_status] || '未知状态'} · 审核：{reviewStatusLabels[version.review_status] || '未知状态'}</p></div>{version.guard_status === 'passed' && version.review_status === 'approved' && <div className="flex flex-wrap gap-2"><a className="btn-secondary" href={`/api/resume-versions/${version.id}/preview`} target="_blank" rel="noreferrer">预览单页版</a><a className="btn-secondary" href={`/api/resume-versions/${version.id}/download?format=html`}>下载 HTML</a><a className="btn-secondary" href={`/api/resume-versions/${version.id}/download`}>下载 DOCX</a></div>}</article>) : <Empty title="还没有岗位定制版本。" />}</div></section>
  </>
}

function ResumeCard({ resume }: { resume: Resume }) {
  const client = useQueryClient()
  const [analysis, setAnalysis] = useState<any>()
  const facts = useQuery({ queryKey: ['facts', resume.id], queryFn: () => api<any>(`/api/resumes/${resume.id}/facts`) })
  const confirmAll = useMutation({ mutationFn: () => api(`/api/resumes/${resume.id}/confirm-facts`, { method: 'POST' }), onSuccess: () => { client.invalidateQueries({ queryKey: ['resumes'] }); client.invalidateQueries({ queryKey: ['facts', resume.id] }) } })
  const analyze = useMutation({ mutationFn: () => api<any>(`/api/resumes/${resume.id}/analysis`, { method: 'POST' }), onSuccess: setAnalysis })
  return <article className="card"><div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-bold">{resume.display_name}</h2><p className="text-sm text-black/50">解析状态：{parseStatusLabels[resume.parse_status] || '未知状态'}</p></div><div className="flex gap-2"><button className="btn-secondary" disabled={analyze.isPending} onClick={() => analyze.mutate()}>{analyze.isPending ? '分析中…' : '分析岗位方向'}</button><button className="btn-secondary" onClick={() => confirmAll.mutate()}>{resume.facts_confirmed_at ? '已确认' : '确认全部事实'}</button></div></div>
    {analysis && <section className="mt-4 rounded-xl border border-sage/20 bg-green-50/50 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-bold">简历方向建议</h3><span className="badge">建议稿 · 非事实结论</span></div><p className="mt-2 text-sm">{analysis.summary}</p>{analysis.requires_fact_confirmation && <p className="mt-2 text-sm text-amber-800">部分事实尚未确认，请先核对事实库再生成定制简历。</p>}<div className="mt-3 grid gap-3 md:grid-cols-2">{analysis.role_suggestions.map((item: any) => <div className="rounded-lg bg-white p-3" key={item.role}><b>{item.role}</b><p className="mt-1 text-sm text-black/60">{item.reason}</p><p className="mt-2 text-xs text-sage">搜索词：{item.search_keywords.join(' / ')}</p></div>)}</div>{analysis.risks.length > 0 && <p className="mt-3 text-sm text-amber-800">注意：{analysis.risks.join('；')}</p>}</section>}
    {analyze.error && <div className="mt-3"><ErrorState error={analyze.error} /></div>}
    <details className="mt-4"><summary className="cursor-pointer text-sage">查看与编辑事实库（{facts.data?.total ?? 0}）</summary><div className="mt-3 space-y-2">{facts.data?.items?.map((fact: any) => <FactRow key={fact.id} fact={fact} resumeId={resume.id} />)}</div><NewFactForm resumeId={resume.id} /></details></article>
}

function FactRow({ fact, resumeId }: { fact: any; resumeId: string }) {
  const client = useQueryClient()
  const [value, setValue] = useState(fact.value_json.text || '')
  const mutation = useMutation({ mutationFn: ({ action }: { action: 'save' | 'confirm' | 'reject' }) => action === 'save' ? api(`/api/resume-facts/${fact.id}`, { method: 'PATCH', body: JSON.stringify({ value_json: { ...fact.value_json, text: value } }) }) : api(`/api/resume-facts/${fact.id}/${action}`, { method: 'POST' }), onSuccess: () => client.invalidateQueries({ queryKey: ['facts', resumeId] }) })
  return <div className="rounded-xl bg-cream p-3"><input className="field text-sm" value={value} onChange={(event) => setValue(event.target.value)} /><div className="mt-2 flex flex-wrap items-center gap-2"><span className="badge">{factStatusLabels[fact.verification_status] || '未知状态'}</span><button className="text-sm text-sage" onClick={() => mutation.mutate({ action: 'save' })}>保存修改</button><button className="text-sm text-sage" onClick={() => mutation.mutate({ action: 'confirm' })}>确认</button><button className="text-sm text-red-700" onClick={() => mutation.mutate({ action: 'reject' })}>拒绝</button></div>{mutation.error && <ErrorState error={mutation.error} />}</div>
}

function NewFactForm({ resumeId }: { resumeId: string }) {
  const client = useQueryClient()
  const [text, setText] = useState('')
  const [category, setCategory] = useState('projects')
  const create = useMutation({
    mutationFn: () => api(`/api/resumes/${resumeId}/facts`, { method: 'POST', body: JSON.stringify({ category, label: text.slice(0, 30), value_json: { text }, source_text: '用户主动补充' }) }),
    onSuccess: () => { setText(''); client.invalidateQueries({ queryKey: ['facts', resumeId] }); client.invalidateQueries({ queryKey: ['resumes'] }) },
  })
  return <form className="mt-4 rounded-xl border border-dashed border-sage/40 p-3" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><h3 className="font-semibold">补充真实经历</h3><p className="mt-1 text-xs text-black/50">仅填写真实完成且可核对的事实，新增后仍需确认。</p><div className="mt-3 grid gap-2 md:grid-cols-[160px_1fr_auto]"><select aria-label="事实类型" className="field" value={category} onChange={(event) => setCategory(event.target.value)}><option value="projects">个人或课程项目</option><option value="employment">工作或实习</option><option value="education">教育经历</option><option value="skills">技能</option><option value="certificates">证书</option><option value="other">其他事实</option></select><input aria-label="新增事实内容" className="field" value={text} onChange={(event) => setText(event.target.value)} placeholder="描述真实动作、产物和证据" /><button className="btn" disabled={!text.trim() || create.isPending}>加入事实库</button></div>{create.error && <ErrorState error={create.error} />}</form>
}
