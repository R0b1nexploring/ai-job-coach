import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Job, ListResponse, Match, Resume } from '../types'
import { Empty, ErrorState, Loading } from '../components/States'
import { dimensionLabels, reviewStatusLabels } from '../app/labels'

export function Jobs() {
  const client = useQueryClient()
  const [raw, setRaw] = useState('')
  const [company, setCompany] = useState('')
  const [title, setTitle] = useState('')
  const [city, setCity] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [publishedAt, setPublishedAt] = useState('')
  const [discoveryProvider, setDiscoveryProvider] = useState('sample')
  const [sourceKey, setSourceKey] = useState('')
  const [resumeId, setResumeId] = useState('')
  const [message, setMessage] = useState('')
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api<ListResponse<Job>>('/api/jobs') })
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: () => api<ListResponse<Resume>>('/api/resumes') })
  const create = useMutation({
    mutationFn: () => api<Job>('/api/jobs/import-text', { method: 'POST', body: JSON.stringify({ raw_jd: raw, company_name: company, title, city, source_url: sourceUrl, published_at: publishedAt ? `${publishedAt}T00:00:00Z` : null }) }),
    onSuccess: () => { setRaw(''); setSourceUrl(''); setPublishedAt(''); setMessage('岗位已结构化。'); client.invalidateQueries({ queryKey: ['jobs'] }) },
  })
  const match = useMutation({
    mutationFn: (jobId: string) => api<Match>('/api/matches', { method: 'POST', body: JSON.stringify({ job_id: jobId, resume_id: resumeId || resumes.data?.items[0]?.id }) }),
    onSuccess: (data) => { setMessage(`匹配完成：${data.total_score} 分，${data.recommendation}`); client.invalidateQueries({ queryKey: ['matches'] }) },
  })
  const discover = useMutation({
    mutationFn: () => api<any>('/api/jobs/discover', { method: 'POST', body: JSON.stringify({ resume_id: resumeId || resumes.data?.items[0]?.id, provider: discoveryProvider, source_key: sourceKey, limit: 10 }) }),
    onSuccess: (data) => { setMessage(data.fallback_used ? `公开来源暂时不可用，已安全回退到本地样例：${data.source_error}` : `已发现并保存 ${data.total} 个相关岗位，请打开公开来源复核。`); client.invalidateQueries({ queryKey: ['jobs'] }) },
  })
  const sourceRequired = ['greenhouse', 'lever', 'public_jsonld'].includes(discoveryProvider)
  const sourceLabel = discoveryProvider === 'public_jsonld' ? '公开招聘页 URL' : '企业标识'
  return <><span className="badge">人工导入 · 不绕过平台限制</span><h1 className="mt-3 text-4xl font-black">岗位库</h1>
    <section className="card mt-6"><div className="flex flex-wrap items-end gap-3"><label className="min-w-52 flex-1"><span className="label">用于推荐的简历</span><select aria-label="用于推荐的简历" className="field" value={resumeId} onChange={(event) => setResumeId(event.target.value)}><option value="">使用最新简历</option>{resumes.data?.items.map((resume) => <option key={resume.id} value={resume.id}>{resume.display_name}</option>)}</select></label><label className="min-w-52 flex-1"><span className="label">公开岗位来源</span><select aria-label="公开岗位来源" className="field" value={discoveryProvider} onChange={(event) => setDiscoveryProvider(event.target.value)}><option value="sample">本地受控样例</option><option value="public_catalog">工程类公开企业职位合集</option><option value="greenhouse">指定 Greenhouse 企业招聘页</option><option value="lever">指定 Lever 企业招聘页</option><option value="public_jsonld">白名单公开招聘页（JSON-LD）</option></select></label>{sourceRequired && <label className="min-w-52 flex-1"><span className="label">{sourceLabel}</span><input className="field" type={discoveryProvider === 'public_jsonld' ? 'url' : 'text'} value={sourceKey} onChange={(event) => setSourceKey(event.target.value)} placeholder={discoveryProvider === 'public_jsonld' ? 'https://careers.example.com/jobs/123' : '例如企业招聘页 URL 中的名称'} /></label>}<button className="btn" disabled={!resumes.data?.items.length || discover.isPending || (sourceRequired && !sourceKey.trim())} onClick={() => discover.mutate()}>{discover.isPending ? '正在读取…' : '按简历发现岗位'}</button></div><p className="mt-3 text-xs text-black/50">仅读取企业公开招聘接口或白名单页面中的 JobPosting 结构化数据，不自动登录、不处理验证码。岗位内容入库后仍需打开来源人工核对。</p>{discover.error && <div className="mt-3"><ErrorState error={discover.error} /></div>}</section>
    <div className="mt-6 grid gap-6 lg:grid-cols-[.9fr_1.1fr]"><form className="card space-y-3" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><h2 className="text-xl font-bold">粘贴 JD</h2><input className="field" placeholder="公司名称" value={company} onChange={(event) => setCompany(event.target.value)} /><input className="field" placeholder="岗位名称" value={title} onChange={(event) => setTitle(event.target.value)} /><div className="grid gap-3 sm:grid-cols-2"><input className="field" placeholder="城市（待确认可留空）" value={city} onChange={(event) => setCity(event.target.value)} /><input aria-label="岗位发布日期" className="field" type="date" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} /></div><input className="field" type="url" placeholder="公开来源链接（可选）" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /><textarea className="field min-h-48" placeholder="粘贴完整岗位描述（至少 10 个字）" value={raw} onChange={(event) => setRaw(event.target.value)} /><button className="btn" disabled={raw.length < 10 || create.isPending}>导入并结构化</button>{(create.error || match.error) && <ErrorState error={create.error || match.error} />}</form>
      <div className="space-y-3">{message && <p className="rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}{jobs.data?.items.length ? jobs.data.items.map((job) => <article className="card" key={job.id}><div className="flex justify-between gap-3"><div><h2 className="font-bold">{job.company_name} · {job.title}</h2><p className="text-sm text-black/50">{job.city || '城市待确认'} · {job.published_at ? `发布于 ${new Date(job.published_at).toLocaleDateString('zh-CN')}` : '发布日期待确认'} · {job.keywords_json.join(' / ') || '待人工补充关键词'}</p>{job.source_url && <a className="mt-2 inline-block text-sm text-sage" href={job.source_url} target="_blank" rel="noreferrer">打开公开来源</a>}</div><button className="btn-secondary" disabled={!resumes.data?.items[0]} onClick={() => match.mutate(job.id)}>生成匹配</button></div></article>) : <Empty title="还没有岗位，粘贴一个公开 JD。" />}</div>
    </div><Matches /></>
}

function Matches() {
  const query = useQuery({ queryKey: ['matches'], queryFn: () => api<ListResponse<Match>>('/api/matches') })
  if (!query.data?.items.length) return null
  return <section className="mt-8"><h2 className="text-2xl font-bold">最近匹配</h2><div className="mt-4 grid gap-4 md:grid-cols-3">{query.data.items.map((item) => <Link to={`/app/matches/${item.id}`} className="card hover:border-sage" key={item.id}><p className="text-4xl font-black">{item.total_score}</p><p className="badge mt-3">{item.recommendation}</p></Link>)}</div></section>
}

export function MatchDetail() {
  const { id } = useParams()
  const [message, setMessage] = useState('')
  const query = useQuery({ queryKey: ['match', id], queryFn: () => api<Match>(`/api/matches/${id}`) })
  const versions = useQuery({ queryKey: ['resume-versions'], queryFn: () => api<ListResponse<any>>('/api/resume-versions') })
  const channels = useQuery({ queryKey: ['channels'], queryFn: () => api<ListResponse<any>>('/api/channels') })
  if (query.isLoading || channels.isLoading) return <Loading text="正在加载报告…" />
  if (query.error || channels.error) return <ErrorState error={query.error || channels.error} />
  const data = query.data!
  return <><Link to="/app/jobs" className="text-sage">← 返回岗位</Link>{message && <p className="mt-4 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
    <div className="mt-5 grid gap-5 lg:grid-cols-[.65fr_1.35fr]"><aside className="card bg-sage text-white"><p className="opacity-70">综合匹配</p><p className="mt-4 text-7xl font-black">{data.total_score}</p><h1 className="mt-2 text-2xl font-bold">{data.recommendation}</h1><p className="mt-5 text-sm opacity-80">{data.ai_explanation_json.summary}</p></aside><main className="space-y-5"><section className="card"><h2 className="font-bold">六项评分</h2><div className="mt-4 grid grid-cols-2 gap-3">{Object.entries(data.dimension_scores_json).map(([key, value]) => <div key={key} className="rounded-xl bg-cream p-3"><p className="text-xs text-black/50">{dimensionLabels[key] || '其他维度'}</p><b className="text-2xl">{value}</b></div>)}</div></section><section className="card"><h2 className="font-bold">能力缺口</h2>{data.gaps_json.length ? <ul className="mt-3 space-y-2">{data.gaps_json.map((gap: any, index) => <li key={index}>△ {gap.requirement}：{gap.action}</li>)}</ul> : <p className="mt-2 text-black/50">未发现明确缺口。</p>}</section><section className="card"><h2 className="font-bold">待确认项</h2><p className="mt-2">{data.confirmations_json.join('；') || '暂无'}</p></section><MatchActions match={data} versions={(versions.data?.items || []).filter((item: any) => item.base_resume_id === data.resume_id && item.job_id === data.job_id)} channels={(channels.data?.items || []).filter((item: any) => item.verify_status !== 'dead')} setMessage={setMessage} /></main></div>
  </>
}

function MatchActions({ match, versions, channels, setMessage }: {
  match: Match
  versions: any[]
  channels: any[]
  setMessage: (message: string) => void
}) {
  const client = useQueryClient()
  const [warningVersion, setWarningVersion] = useState<any | null>(null)
  const [channelId, setChannelId] = useState('')
  const createTargets = useMutation({
    mutationFn: () => api<any>(`/api/matches/${match.id}/capability-targets`, { method: 'POST' }),
    onSuccess: (data) => {
      setMessage(`已生成 ${data.total} 个学习目标。`)
      client.invalidateQueries({ queryKey: ['capability-targets'] })
    },
  })
  const generate = useMutation({
    mutationFn: (kind: 'target' | 'submittable') => api<any>('/api/resume-versions', {
      method: 'POST',
      headers: { 'Idempotency-Key': `web-version-${match.id}-${kind}-${Date.now()}` },
      body: JSON.stringify({
        base_resume_id: match.resume_id,
        job_id: match.job_id,
        match_id: match.id,
        kind,
      }),
    }),
    onSuccess: (data) => {
      setMessage(data.guard_status === 'passed' ? '简历已生成，事实检查通过。' : '检测到未经确认的新事实，已拦截。')
      client.invalidateQueries({ queryKey: ['resume-versions'] })
    },
  })
  const submitReview = useMutation({
    mutationFn: (version: any) => api<any>(`/api/resume-versions/${version.id}/submit-review`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('已提交顾问审核，通过后可以下载或加入投递。')
      client.invalidateQueries({ queryKey: ['resume-versions'] })
    },
  })
  const queue = useMutation({
    mutationFn: (version: any) => api<any>('/api/applications', {
      method: 'POST',
      headers: { 'Idempotency-Key': `web-application-${match.id}-${version.id}-${Date.now()}` },
      body: JSON.stringify({ job_id: match.job_id, resume_version_id: version.id, channel_id: channelId || null }),
    }),
    onSuccess: () => setMessage('已加入投递队列。'),
  })
  const requestQueue = (version: any) => {
    const warningKey = `application-warning:${version.id}:${match.job_id}`
    if (version.unachieved_count > 0 && !localStorage.getItem(warningKey)) {
      setWarningVersion(version)
      return
    }
    queue.mutate(version)
  }
  const continueQueue = () => {
    if (!warningVersion) return
    localStorage.setItem(`application-warning:${warningVersion.id}:${match.job_id}`, 'confirmed')
    queue.mutate(warningVersion)
    setWarningVersion(null)
  }
  const unachievedItems = warningVersion?.content_json?.sections?.flatMap((section: any) => (
    section.items.flatMap((item: any) => (
      (item.bullets || []).filter((bullet: any) => bullet.achieved === false).map((bullet: any) => bullet.text)
    ))
  )) || []
  const error = createTargets.error || generate.error || submitReview.error || queue.error

  return (
    <section className="card">
      <h2 className="font-bold">下一步</h2>
      <label className="mt-4 block">
        <span className="label">加入投递队列时使用的渠道（可选）</span>
        <select aria-label="投递渠道" className="field" value={channelId} onChange={(event) => setChannelId(event.target.value)}>
          <option value="">暂不关联具体入口</option>
          {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.company_name} · {channel.channel_type === 'email' ? '邮箱' : channel.channel_type === 'career_page' ? '招聘页' : '表单'}</option>)}
        </select>
      </label>
      <div className="mt-4 flex flex-wrap gap-3">
        {match.gaps_json.length > 0 && (
          <button className="btn-secondary" disabled={createTargets.isPending} onClick={() => createTargets.mutate()}>
            生成学习目标
          </button>
        )}
        <Link className="btn-secondary" to={`/app/capability-targets?job_id=${match.job_id}`}>查看学习目标</Link>
        <button className="btn-secondary" disabled={generate.isPending} onClick={() => generate.mutate('target')}>
          生成蓝图简历
        </button>
        <button className="btn" disabled={generate.isPending} onClick={() => generate.mutate('submittable')}>
          生成可投递简历
        </button>
      </div>
      <div className="mt-5 space-y-3">
        {versions.map((version) => (
          <div className="rounded-xl border border-black/10 p-3" key={version.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${version.kind === 'target' ? 'bg-amber-50 text-amber-800' : 'bg-green-50 text-green-700'}`}>
                  {version.kind === 'target' ? `蓝图 · ${version.unachieved_count} 条未达成` : '可投递 · 全部已确认'}
                </span>
                <p className="mt-2 text-sm text-black/55">审核状态：{reviewStatusLabels[version.review_status] || '未知状态'}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {version.guard_status === 'passed' && ['draft', 'user_review', 'rejected'].includes(version.review_status) && (
                  <button className="btn-secondary" onClick={() => submitReview.mutate(version)}>提交顾问审核</button>
                )}
                {version.review_status === 'advisor_review' && <span className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">等待顾问审核</span>}
                {version.review_status === 'approved' && (
                  <>
                    <a className="btn-secondary" href={`/api/resume-versions/${version.id}/preview`} target="_blank" rel="noreferrer">预览单页版</a>
                    <a className="btn-secondary" href={`/api/resume-versions/${version.id}/download?format=html`}>下载 HTML</a>
                    <a className="btn-secondary" href={`/api/resume-versions/${version.id}/download`}>下载 DOCX</a>
                    <button className="btn" onClick={() => requestQueue(version)}>加入投递队列</button>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      {error && <div className="mt-4"><ErrorState error={error} /></div>}
      {warningVersion && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-5" role="dialog" aria-modal="true" aria-label="未达成目标投递提示">
          <section className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
            <h2 className="text-xl font-bold">这份蓝图含未达成目标</h2>
            <p className="mt-2 text-sm text-black/65">
              共 {warningVersion.unachieved_count} 条。这些内容会明确标为“未达成”，也最可能在面试中被深挖。
            </p>
            <ul className="mt-3 space-y-1 text-sm text-amber-900">
              {unachievedItems.map((item: string) => <li key={item}>△ {item}</li>)}
            </ul>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Link className="btn-secondary" to="/app/interviews">查看面试指南</Link>
              <button className="btn" onClick={continueQueue}>继续投递</button>
            </div>
          </section>
        </div>
      )}
    </section>
  )
}
