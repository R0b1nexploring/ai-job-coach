import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, ApiRequestError } from '../api/client'
import type { ListResponse, MissingInformation, Resume } from '../types'
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
  return <><div className="flex flex-wrap items-end justify-between gap-4"><div><span className="badge">事实优先</span><h1 className="page-title mt-3">简历与事实库</h1></div><label className="btn cursor-pointer">上传 DOCX / PDF<input className="hidden" type="file" accept=".docx,.pdf" onChange={(event) => event.target.files?.[0] && upload.mutate(event.target.files[0])} /></label></div>
    {(upload.error || resumes.error || versions.error) && <div className="mt-5"><ErrorState error={upload.error || resumes.error || versions.error} /></div>}{message && <p className="mt-5 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
    <div className="mt-6 space-y-4">{resumes.data?.items.length ? resumes.data.items.map((resume) => <ResumeCard key={resume.id} resume={resume} />) : <Empty title="还没有简历，上传一份开始分析。" />}</div>
    <section className="mt-10"><h2 className="text-2xl font-bold">定制版本</h2><div className="mt-4 space-y-3">{versions.data?.items?.length ? versions.data.items.map((version: any) => <VersionCard key={version.id} version={version} />) : <Empty title="还没有岗位定制版本。" />}</div></section>
  </>
}

function VersionCard({ version }: { version: any }) {
  const client = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [headline, setHeadline] = useState(version.content_json.headline || version.title)
  const [sections, setSections] = useState(version.content_json.sections || [])
  const [gaps, setGaps] = useState((version.content_json.excluded_gaps || []).join('、'))
  const save = useMutation({
    mutationFn: () => api(`/api/resume-versions/${version.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        ...version.content_json,
        headline,
        sections,
        excluded_gaps: gaps.split(/[、,，\n]/).map((item: string) => item.trim()).filter(Boolean),
      }),
    }),
    onSuccess: () => { setEditing(false); client.invalidateQueries({ queryKey: ['resume-versions'] }) },
  })
  const submitReview = useMutation({
    mutationFn: () => api(`/api/resume-versions/${version.id}/submit-review`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['resume-versions'] }),
  })
  const updateText = (sectionIndex: number, itemIndex: number, bulletIndex: number, text: string) => {
    setSections((current: any[]) => current.map((section, currentSectionIndex) => {
      if (currentSectionIndex !== sectionIndex) return section
      return {
        ...section,
        items: section.items.map((item: any, currentItemIndex: number) => {
          if (currentItemIndex !== itemIndex) return item
          if (!item.bullets) return { ...item, text }
          return {
            ...item,
            bullets: item.bullets.map((bullet: any, currentBulletIndex: number) => (
              currentBulletIndex === bulletIndex ? { ...bullet, text } : bullet
            )),
          }
        }),
      }
    }))
  }
  const isTarget = version.kind === 'target'
  const canSubmit = version.guard_status === 'passed' && ['draft', 'user_review', 'rejected'].includes(version.review_status)

  return (
    <article className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <b>{version.title}</b>
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${isTarget ? 'bg-amber-50 text-amber-800' : 'bg-green-50 text-green-700'}`}>
              {isTarget ? '蓝图 · 对照 JD 的差距' : '可投递 · 全部已确认'}
            </span>
          </div>
          <p className="mt-1 text-sm text-black/50">
            事实检查：{guardStatusLabels[version.guard_status] || '未知状态'} · 审核：{reviewStatusLabels[version.review_status] || '未知状态'}
          </p>
          {isTarget && (
            <Link className="mt-2 inline-block text-sm text-amber-800 underline" to={`/app/capability-targets?job_id=${version.job_id}`}>
              {version.unachieved_count} 条未达成，前往学习目标
            </Link>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {version.review_status !== 'approved' && (
            <button className="btn-secondary" onClick={() => setEditing((value) => !value)}>
              {editing ? '收起修改' : '修改内容'}
            </button>
          )}
          {canSubmit && <button className="btn" onClick={() => submitReview.mutate()}>提交顾问审核</button>}
          {version.guard_status === 'passed' && (
            <>
              <a className="btn-secondary" href={`/api/resume-versions/${version.id}/preview`} target="_blank" rel="noreferrer">预览单页版</a>
              <a className="btn-secondary" href={`/api/resume-versions/${version.id}/download?format=html`}>下载 HTML</a>
              <a className="btn-secondary" href={`/api/resume-versions/${version.id}/download`}>下载 DOCX</a>
            </>
          )}
        </div>
      </div>
      <ResumeDraft content={version.content_json} />
      {editing && (
        <div className="mt-4 space-y-4 rounded-xl border border-sage/20 bg-green-50/40 p-4">
          <p className="text-xs text-black/55">只能压缩、排序和改写已有来源；未达成目标必须继续明确标记。保存后会重新执行事实检查。</p>
          <label>
            <span className="label">简历标题</span>
            <input aria-label="简历标题" className="field" value={headline} onChange={(event) => setHeadline(event.target.value)} />
          </label>
          {sections.map((section: any, sectionIndex: number) => (
            <section key={`${section.name}-${sectionIndex}`}>
              <h3 className="font-semibold">{section.name}</h3>
              <div className="mt-2 space-y-2">
                {section.items.flatMap((item: any, itemIndex: number) => (
                  item.bullets?.length
                    ? item.bullets.map((bullet: any, bulletIndex: number) => (
                      <textarea
                        aria-label={`${section.name}第${itemIndex + 1}项第${bulletIndex + 1}条`}
                        className="field min-h-20"
                        key={`${section.name}-${itemIndex}-${bulletIndex}`}
                        value={bullet.text}
                        onChange={(event) => updateText(sectionIndex, itemIndex, bulletIndex, event.target.value)}
                      />
                    ))
                    : [(
                      <textarea
                        aria-label={`${section.name}第${itemIndex + 1}条`}
                        className="field min-h-24"
                        key={`${section.name}-${itemIndex}`}
                        value={item.text || ''}
                        onChange={(event) => updateText(sectionIndex, itemIndex, 0, event.target.value)}
                      />
                    )]
                ))}
              </div>
            </section>
          ))}
          <label>
            <span className="label">能力缺口（用顿号分隔）</span>
            <textarea aria-label="能力缺口" className="field min-h-20" value={gaps} onChange={(event) => setGaps(event.target.value)} />
          </label>
          <button className="btn" disabled={!headline.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? '正在检查…' : '保存修改并重新检查'}
          </button>
          {(save.error || submitReview.error) && <ErrorState error={save.error || submitReview.error} />}
        </div>
      )}
      {!editing && submitReview.error && <div className="mt-4"><ErrorState error={submitReview.error} /></div>}
    </article>
  )
}

function ResumeCard({ resume }: { resume: Resume }) {
  const client = useQueryClient()
  const [analysis, setAnalysis] = useState<any>()
  const [blockingMissing, setBlockingMissing] = useState<MissingInformation[]>([])
  const [message, setMessage] = useState('')
  const facts = useQuery({ queryKey: ['facts', resume.id], queryFn: () => api<any>(`/api/resumes/${resume.id}/facts`) })
  const confirmAll = useMutation({
    mutationFn: () => api(`/api/resumes/${resume.id}/confirm-facts`, { method: 'POST' }),
    onSuccess: () => {
      setBlockingMissing([])
      setMessage('完整事实已确认，可以开始匹配与简历生成。')
      client.invalidateQueries({ queryKey: ['resumes'] })
      client.invalidateQueries({ queryKey: ['facts', resume.id] })
    },
    onError: (error) => {
      if (error instanceof ApiRequestError && error.code === 'RESUME_FACTS_INCOMPLETE') {
        setBlockingMissing((error.details.missing_information || []) as MissingInformation[])
      }
    },
  })
  const analyze = useMutation({ mutationFn: () => api<any>(`/api/resumes/${resume.id}/analysis`, { method: 'POST' }), onSuccess: setAnalysis })
  const missing = blockingMissing.length ? blockingMissing : (resume.missing_information_json || [])
  return <article className="card"><div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-bold">{resume.display_name}</h2><p className="text-sm text-black/50">解析状态：{parseStatusLabels[resume.parse_status] || '未知状态'}</p></div><div className="flex gap-2"><button className="btn-secondary" disabled={analyze.isPending} onClick={() => analyze.mutate()}>{analyze.isPending ? '分析中…' : '分析岗位方向'}</button><button className="btn-secondary" disabled={!!resume.facts_confirmed_at || confirmAll.isPending} onClick={() => confirmAll.mutate()}>{resume.facts_confirmed_at ? '完整事实已确认' : '确认所有完整事实'}</button></div></div>
    {message && <p className="mt-3 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
    {missing.length > 0 && <ClarificationForm resumeId={resume.id} missing={missing} onCompleted={() => { setBlockingMissing([]); setMessage('待补信息已保存，请再次确认所有完整事实。') }} />}
    {analysis && <section className="mt-4 rounded-xl border border-sage/20 bg-green-50/50 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-bold">简历方向建议</h3><span className="badge">建议稿 · 非事实结论</span></div><p className="mt-2 text-sm">{analysis.summary}</p>{analysis.requires_fact_confirmation && <p className="mt-2 text-sm text-amber-800">部分事实尚未确认，请先核对事实库再生成定制简历。</p>}<div className="mt-3 grid gap-3 md:grid-cols-2">{analysis.role_suggestions.map((item: any) => <div className="rounded-lg bg-white p-3" key={item.role}><b>{item.role}</b><p className="mt-1 text-sm text-black/60">{item.reason}</p><p className="mt-2 text-xs text-sage">搜索词：{item.search_keywords.join(' / ')}</p></div>)}</div>{analysis.risks.length > 0 && <p className="mt-3 text-sm text-amber-800">注意：{analysis.risks.join('；')}</p>}</section>}
    {(analyze.error || confirmAll.error) && <div className="mt-3"><ErrorState error={analyze.error || confirmAll.error} /></div>}
    <details className="mt-4"><summary className="cursor-pointer text-sage">查看与编辑事实库（{facts.data?.total ?? 0}）</summary><div className="mt-3 space-y-2">{facts.data?.items?.map((fact: any) => <FactRow key={fact.id} fact={fact} resumeId={resume.id} />)}</div><NewFactForm resumeId={resume.id} /></details></article>
}

function ClarificationForm({ resumeId, missing, onCompleted }: {
  resumeId: string
  missing: MissingInformation[]
  onCompleted: () => void
}) {
  const client = useQueryClient()
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const clarification = useMutation({
    mutationFn: () => api(`/api/resumes/${resumeId}/answer-clarifications`, {
      method: 'POST',
      body: JSON.stringify(missing.map((item) => ({
        fact_id: item.fact_id,
        field: item.field,
        value: answers[`${item.fact_id}:${item.field}`]?.trim(),
      }))),
    }),
    onSuccess: () => {
      onCompleted()
      client.invalidateQueries({ queryKey: ['resumes'] })
      client.invalidateQueries({ queryKey: ['facts', resumeId] })
    },
  })
  const complete = missing.every((item) => answers[`${item.fact_id}:${item.field}`]?.trim())

  return (
    <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
      <h3 className="font-bold text-amber-900">先补充关键事实</h3>
      <p className="mt-1 text-sm text-amber-800">缺少这些字段时不会批量确认，避免把不完整内容误当成已核实事实。</p>
      <div className="mt-3 space-y-3">
        {missing.map((item) => {
          const key = `${item.fact_id}:${item.field}`
          return (
            <label key={key}>
              <span className="label">{item.question}</span>
              <input
                aria-label={item.question}
                className="field"
                value={answers[key] || ''}
                onChange={(event) => setAnswers({ ...answers, [key]: event.target.value })}
                placeholder={item.field.includes('date') ? 'YYYY-MM；结束时间可填“至今”' : '填写原简历可核对的信息'}
              />
            </label>
          )
        })}
      </div>
      <button className="btn mt-4" disabled={!complete || clarification.isPending} onClick={() => clarification.mutate()}>
        保存待补信息
      </button>
      {clarification.error && <div className="mt-3"><ErrorState error={clarification.error} /></div>}
    </section>
  )
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

export function ResumeDraft({ content }: { content: any }) {
  const sections = content?.sections || []
  const gap = content?.gap_summary
  if (!sections.length && !gap?.reasons?.length) return null
  return (
    <div className="mt-4 space-y-4 rounded-xl bg-cream p-4 text-sm">
      {content.headline && <p className="text-lg font-bold">意向：{content.headline}</p>}
      {content.kind === 'target' && gap?.reasons?.length ? (
        <div className="rounded-xl bg-amber-50 p-3 text-amber-950">
          <p className="font-bold">{gap.title || '对照岗位还缺什么'}</p>
          <p className="mt-1 text-xs text-amber-900/80">下面是按 JD 画出的差距，未达成条目不是你已经做过的经历。</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {gap.reasons.map((reason: string) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      ) : null}
      {sections.map((section: any, sectionIndex: number) => (
        <section key={`${section.name}-${sectionIndex}`}>
          <h3 className="font-semibold">{section.name}</h3>
          {section.presentation === 'tags' || section.name === '技能' || section.name === '技能证书' ? (
            <p className="mt-2 text-black/80">
              {(section.items || []).flatMap((item: any) => item.bullets || []).map((bullet: any) => (
                bullet.achieved === false ? `[未达成 · 学习目标] ${bullet.text}` : bullet.text
              )).filter(Boolean).join(' / ')}
            </p>
          ) : (section.items || []).map((item: any, itemIndex: number) => (
            <div className="mt-2" key={`${item.organization || item.text || 'item'}-${itemIndex}`}>
              {(item.organization || item.role_title || item.start_date) && (
                <p className="text-black/55">
                  {(section.name === '教育背景'
                    ? [item.organization, item.role_title, [item.start_date, item.end_date].filter(Boolean).join('–')]
                    : [item.role_title, item.organization, [item.start_date, item.end_date].filter(Boolean).join('–')]
                  ).filter(Boolean).join('｜').replace(/(\d{4})-(\d{2})(?:-\d{2})?/g, '$1.$2')}
                </p>
              )}
              <ul className="mt-1 list-disc space-y-1 pl-5">
                {(item.bullets || (item.text ? [{ text: item.text, achieved: true }] : [])).map((bullet: any, bulletIndex: number) => (
                  <li key={bulletIndex} className={bullet.achieved === false ? 'text-black/45' : ''}>
                    {bullet.achieved === false ? '[未达成 · 学习目标] ' : ''}
                    {bullet.text}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}
