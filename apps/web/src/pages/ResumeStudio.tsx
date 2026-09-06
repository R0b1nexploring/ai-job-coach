import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'
import type { ExperienceEntry, Job, ListResponse, Resume } from '../types'

type Profile = {
  id: string
  title: string
  mode: string
  snapshot_json: { requirements?: Array<{ id: string; text: string; priority: string }> }
}
type Bundle = {
  id: string
  status: string
  error?: string
  can_retry?: boolean
  versions: Record<string, { id: string; kind: string; status: string; content_hash: string }>
  guides: Record<string, { id: string; status: string }>
  generation_metadata_json?: { degraded?: boolean; writer?: Record<string, string> }
}
type StudioVersion = {
  id: string
  kind: string
  title: string
  guard_status: string
  content_hash: string
  quality_report_json: {
    status?: string
    hard_passed?: boolean
    issues?: string[]
    reviewer?: string
    reviewer_note?: string
    dimensions?: Record<string, { score: number }>
  }
  content_json: {
    headline?: string
    sections?: Array<{
      name: string
      items: Array<{
        organization?: string
        role_title?: string
        bullets?: Array<{
          id: string
          text: string
          achieved?: boolean
          locked?: boolean
          source_fact_ids?: string[]
          verification_status?: string
        }>
      }>
    }>
  }
}

export function ResumeStudio() {
  const client = useQueryClient()
  const [jdText, setJdText] = useState('')
  const [jobIds, setJobIds] = useState<string[]>([])
  const [selectedProfile, setSelectedProfile] = useState('')
  const [selectedResume, setSelectedResume] = useState('')
  const [bundleId, setBundleId] = useState('')
  const [kind, setKind] = useState<'submittable' | 'target'>('submittable')
  const [message, setMessage] = useState('')
  const [showExperienceForm, setShowExperienceForm] = useState(false)
  const [experienceOrganization, setExperienceOrganization] = useState('')
  const [experienceText, setExperienceText] = useState('')
  const [experienceResult, setExperienceResult] = useState('')
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api<ListResponse<Job>>('/api/jobs') })
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: () => api<ListResponse<Resume>>('/api/resumes') })
  const materials = useQuery({ queryKey: ['experience'], queryFn: () => api<ListResponse<ExperienceEntry>>('/api/experience') })
  const profiles = useQuery({ queryKey: ['target-profiles'], queryFn: () => api<ListResponse<Profile>>('/api/target-profiles') })
  const bundles = useQuery({
    queryKey: ['resume-bundles'],
    queryFn: () => api<ListResponse<Bundle>>('/api/resume-bundles'),
  })
  const bundle = useQuery({
    queryKey: ['resume-bundle', bundleId],
    queryFn: () => api<Bundle>(`/api/resume-bundles/${bundleId}`),
    enabled: Boolean(bundleId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'generating' ? 800 : false
    },
  })
  useEffect(() => {
    if (!bundleId && bundles.data?.items?.[0]?.id) {
      setBundleId(bundles.data.items[0].id)
    }
  }, [bundleId, bundles.data])
  useEffect(() => {
    if (!selectedProfile && profiles.data?.items?.[0]?.id) {
      setSelectedProfile(profiles.data.items[0].id)
    }
  }, [profiles.data, selectedProfile])
  const versionId = bundle.data?.versions?.[kind]?.id || ''
  const version = useQuery({
    queryKey: ['studio-version', versionId],
    queryFn: () => api<StudioVersion>(`/api/resume-versions/${versionId}/studio`),
    enabled: Boolean(versionId),
  })
  const analyzeTarget = useMutation({
    mutationFn: async (raw: string) => {
      const job = await api<Job>('/api/jobs/import-text', {
        method: 'POST',
        body: JSON.stringify({ company_name: '目标公司', title: '目标岗位', raw_jd: raw }),
      })
      const profile = await api<Profile>('/api/target-profiles', {
        method: 'POST',
        body: JSON.stringify({ mode: 'single_jd', job_ids: [job.id] }),
      })
      return { job, profile }
    },
    onSuccess: ({ profile }) => {
      setSelectedProfile(profile.id)
      setJdText('')
      setMessage('岗位已分析，可以直接生成简历。')
      client.invalidateQueries({ queryKey: ['jobs'] })
      client.invalidateQueries({ queryKey: ['target-profiles'] })
    },
  })
  const createProfile = useMutation({
    mutationFn: () => api<Profile>('/api/target-profiles', {
      method: 'POST',
      body: JSON.stringify({
        mode: jobIds.length > 1 ? 'multi_jd' : 'single_jd',
        job_ids: jobIds,
      }),
    }),
    onSuccess: (profile) => {
      setSelectedProfile(profile.id)
      setMessage('目标画像已创建。')
      client.invalidateQueries({ queryKey: ['target-profiles'] })
    },
  })
  const createMaterial = useMutation({
    mutationFn: async () => {
      const row = await api<ExperienceEntry>('/api/experience', {
        method: 'POST',
        body: JSON.stringify({
          kind: 'project',
          title: experienceText.trim().slice(0, 40) || '补充经历',
          organization: experienceOrganization.trim(),
          summary: experienceText.trim(),
          details_json: {
            actions: experienceText.trim(),
            results: experienceResult.trim(),
          },
        }),
      })
      return api<ExperienceEntry>(`/api/experience/${row.id}/confirm`, { method: 'POST' })
    },
    onSuccess: () => {
      setExperienceOrganization('')
      setExperienceText('')
      setExperienceResult('')
      setShowExperienceForm(false)
      setMessage('这段经历已加入生成参考。')
      client.invalidateQueries({ queryKey: ['experience'] })
    },
  })
  const uploadResume = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      return api<Resume>('/api/resumes', { method: 'POST', body })
    },
    onSuccess: (resume) => {
      setSelectedResume(resume.id)
      setMessage('简历已上传并解析。可在本页确认事实，不必回到旧简历页。')
      client.invalidateQueries({ queryKey: ['resumes'] })
    },
  })
  const confirmResume = useMutation({
    mutationFn: (id: string) => api(`/api/resumes/${id}/confirm-facts`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('上传简历的事实已确认。')
      client.invalidateQueries({ queryKey: ['resumes'] })
    },
  })
  const generate = useMutation({
    mutationFn: () => api<Bundle>('/api/resume-bundles', {
      method: 'POST',
      body: JSON.stringify({
        ...(selectedResume ? { base_resume_id: selectedResume } : {}),
        target_profile_id: selectedProfile,
      }),
    }),
    onSuccess: (created) => {
      setBundleId(created.id)
      setMessage(created.status === 'queued' || created.status === 'generating' ? '已排队生成，正在后台处理。' : created.status === 'degraded' ? '已生成基础降级版本，请查看质量提示。' : '双轨简历已生成。')
      client.invalidateQueries({ queryKey: ['resume-bundle'] })
      client.invalidateQueries({ queryKey: ['resume-bundles'] })
    },
  })
  const retry = useMutation({
    mutationFn: () => api<Bundle>(`/api/resume-bundles/${bundleId}/retry`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('已重新排队生成。')
      client.invalidateQueries({ queryKey: ['resume-bundle', bundleId] })
    },
  })
  const lock = useMutation({
    mutationFn: (bulletId: string) => api(`/api/resume-versions/${versionId}/lock`, { method: 'POST', body: JSON.stringify({ bullet_id: bulletId, locked: true }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['studio-version', versionId] }),
  })
  const regenerate = useMutation({
    mutationFn: (payload: { scope: 'all' | 'bullet'; bullet_id?: string }) => api(`/api/resume-versions/${versionId}/regenerate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
    onSuccess: () => {
      setMessage('已重生成并重新校验。')
      client.invalidateQueries({ queryKey: ['studio-version', versionId] })
      client.invalidateQueries({ queryKey: ['resume-bundle', bundleId] })
    },
  })
  const regenerateGuide = useMutation({
    mutationFn: (guideId: string) => api(`/api/interview-guides/${guideId}/regenerate`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('已重新生成面试指南。')
      client.invalidateQueries({ queryKey: ['resume-bundle', bundleId] })
    },
  })
  const ownMaterials = useMemo(() => (materials.data?.items || []).filter((item) => item.is_own), [materials.data?.items])

  if (jobs.isLoading || resumes.isLoading) return <Loading />
  const error = jobs.error || resumes.error || generate.error || createProfile.error || analyzeTarget.error || createMaterial.error || uploadResume.error || retry.error
  const status = bundle.data?.status
  const degraded = status === 'degraded'
  const failed = status === 'failed'
  const pending = status === 'queued' || status === 'generating'
  const content = version.data?.content_json
  const reviewerNote = version.data?.quality_report_json.reviewer_note
  return (
    <>
      <p className="badge">自助简历工作台</p>
      <h1 className="mt-3 text-4xl font-black">一份求职简历，一份蓝图 Plus</h1>
      <p className="mt-3 max-w-3xl text-black/60">粘贴招聘要求，AI 会先理解岗位，再为你生成求职版和提升蓝图。上传简历和补充经历都可以稍后再做。</p>
      {error && <div className="mt-5"><ErrorState error={error} /></div>}
      {message && <p className="mt-5 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
      {degraded && <p className="mt-5 rounded-xl bg-amber-50 p-3 text-amber-800" role="status">当前是基础降级版本，使用本地基础内容，表达质量可能有限。</p>}
      {failed && (
        <p className="mt-5 rounded-xl bg-red-50 p-3 text-red-700" role="alert">
          生成失败：{bundle.data?.error || '请重试。'}
        </p>
      )}
      {pending && <p className="mt-5 rounded-xl bg-slate-50 p-3 text-slate-700">状态：{status === 'queued' ? '排队中' : '生成中'}，完成后会自动刷新。</p>}

      <section className="card mt-8">
        <p className="text-sm font-semibold text-sage">第一步</p>
        <h2 className="mt-1 text-2xl font-bold">你想申请什么岗位？</h2>
        <p className="mt-2 text-sm text-black/55">复制招聘页面里的职位描述，剩下的交给 AI。</p>
        <textarea
          className="field mt-4 min-h-28"
          name="jd-raw"
          placeholder="在这里粘贴职位描述（JD）…"
          value={jdText}
          onChange={(event) => setJdText(event.target.value)}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn" onClick={() => jdText && analyzeTarget.mutate(jdText)} disabled={!jdText.trim() || analyzeTarget.isPending}>
            {analyzeTarget.isPending ? '正在分析…' : '分析这个岗位'}
          </button>
        </div>
        {(profiles.data?.items || []).length > 0 && (
          <details className="mt-5 rounded-xl border border-black/10 bg-black/[0.02] p-3">
            <summary className="cursor-pointer text-sm font-semibold">使用之前分析过的岗位</summary>
            <select className="field mt-3" aria-label="已有岗位目标" value={selectedProfile} onChange={(event) => setSelectedProfile(event.target.value)}>
              {(profiles.data?.items || []).map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.title}</option>
              ))}
            </select>
          </details>
        )}
        {(jobs.data?.items || []).length >= 2 && (
          <details className="mt-3 rounded-xl border border-black/10 p-3">
            <summary className="cursor-pointer text-sm text-black/55">高级：合并多个已有岗位</summary>
            <div className="mt-3 grid max-h-52 gap-2 overflow-auto">
              {(jobs.data?.items || []).map((job) => (
                <label key={job.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={jobIds.includes(job.id)} onChange={() => setJobIds((current) => current.includes(job.id) ? current.filter((id) => id !== job.id) : [...current, job.id])} />
                  {job.company_name} · {job.title}
                </label>
              ))}
            </div>
            <button className="btn-secondary mt-3" onClick={() => createProfile.mutate()} disabled={jobIds.length < 2}>合并所选岗位</button>
          </details>
        )}
      </section>

      <section className="card mt-6">
        <p className="text-sm font-semibold text-sage">可选</p>
        <h2 className="mt-1 text-2xl font-bold">让结果更像你</h2>
        <p className="mt-2 text-sm text-black/55">有现成简历就上传；没有也可以跳过，直接让 AI 先生成一版。</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <label className="btn-secondary cursor-pointer">
            上传现有简历
            <input className="hidden" type="file" accept=".docx,.pdf" onChange={(event) => event.target.files?.[0] && uploadResume.mutate(event.target.files[0])} />
          </label>
          <button className="btn-secondary" onClick={() => setShowExperienceForm((current) => !current)}>
            {showExperienceForm ? '收起' : '补充一段经历'}
          </button>
        </div>
        {showExperienceForm && (
          <div className="mt-4 rounded-xl border border-sage/30 bg-sage/5 p-4">
            <label className="block text-sm font-semibold">在哪里完成的？</label>
            <input className="field mt-1" value={experienceOrganization} onChange={(event) => setExperienceOrganization(event.target.value)} placeholder="例如：学校实验室、某公司或个人项目" />
            <label className="mt-4 block text-sm font-semibold">你具体做了什么？</label>
            <textarea className="field mt-1 min-h-24" value={experienceText} onChange={(event) => setExperienceText(event.target.value)} placeholder="用自己的话描述即可，例如：我用 SolidWorks 完成了装配体建模和工程图。" />
            <label className="mt-4 block text-sm font-semibold">有什么结果？ <span className="font-normal text-black/45">选填</span></label>
            <input className="field mt-1" value={experienceResult} onChange={(event) => setExperienceResult(event.target.value)} placeholder="例如：完成答辩、交付报告或效率提升" />
            <button className="btn mt-4" onClick={() => createMaterial.mutate()} disabled={!experienceOrganization.trim() || !experienceText.trim() || createMaterial.isPending}>保存这段经历</button>
          </div>
        )}
        {(resumes.data?.items || []).length > 0 && (
          <div className="mt-4">
            <label className="text-sm font-semibold" htmlFor="resume-source">用于生成的简历</label>
            <select id="resume-source" className="field mt-1" value={selectedResume} onChange={(event) => setSelectedResume(event.target.value)}>
              <option value="">不使用简历，直接生成</option>
              {(resumes.data?.items || []).map((resume) => <option key={resume.id} value={resume.id}>{resume.display_name}</option>)}
            </select>
            {selectedResume && !(resumes.data?.items || []).find((resume) => resume.id === selectedResume)?.facts_confirmed_at && (
              <button type="button" className="mt-2 text-sm text-sage underline" onClick={() => confirmResume.mutate(selectedResume)}>确认这份简历的内容</button>
            )}
          </div>
        )}
        <details className="mt-4 text-sm text-black/55">
          <summary className="cursor-pointer">已保存的经历与素材（{ownMaterials.length}）</summary>
          <div className="mt-2 grid gap-2">
            {ownMaterials.map((item) => <p key={item.id} className="rounded-lg bg-black/[0.03] px-3 py-2">{item.title}</p>)}
          </div>
        </details>
      </section>

      <section className="card mt-6">
        <p className="text-sm font-semibold text-sage">第二步</p>
        <h2 className="mt-1 text-2xl font-bold">生成你的两份简历</h2>
        <button className="btn mt-4" disabled={!selectedProfile || generate.isPending} onClick={() => generate.mutate()}>生成求职版和蓝图 Plus</button>
        {failed && bundle.data?.can_retry && (
          <button className="btn-secondary mt-3" onClick={() => retry.mutate()}>重试生成</button>
        )}
        {bundle.data && (
          <div className="mt-4 flex gap-2">
            <button className={kind === 'submittable' ? 'btn' : 'btn-secondary'} onClick={() => setKind('submittable')}>求职版</button>
            <button className={kind === 'target' ? 'btn' : 'btn-secondary'} onClick={() => setKind('target')}>蓝图 Plus</button>
          </div>
        )}
        {version.data && (
          <div className="mt-5">
            <p className="text-sm text-black/50">质量状态：{version.data.quality_report_json.status || version.data.guard_status}{reviewerNote ? ` · ${reviewerNote}` : ''}</p>
            <div className="mt-3 rounded-xl border bg-white p-4" data-testid="a4-preview">
              <h3 className="text-xl font-black">{content?.headline}</h3>
              {(content?.sections || []).map((section) => (
                <div key={section.name} className="mt-3">
                  <h4 className="font-bold">{section.name}</h4>
                  {section.items.map((item, itemIndex) => (
                    <ul key={`${section.name}-${itemIndex}`} className="mt-1 list-disc pl-5">
                      {(item.bullets || []).map((bullet) => (
                        <li key={bullet.id}>
                          {bullet.text}{bullet.achieved === false ? '*' : ''}
                          {bullet.verification_status === 'ai_generated' && <span className="ml-2 text-xs text-amber-700">AI 补充 · 待核验</span>}
                          {bullet.source_fact_ids?.length ? <span className="ml-2 text-xs text-black/40">来源 {bullet.source_fact_ids.join(',')}</span> : null}
                          <button className="ml-2 text-xs underline" onClick={() => lock.mutate(bullet.id)}>{bullet.locked ? '已锁定' : '锁定'}</button>
                          {!bullet.locked && (
                            <button className="ml-2 text-xs underline" onClick={() => regenerate.mutate({ scope: 'bullet', bullet_id: bullet.id })}>重写本条</button>
                          )}
                        </li>
                      ))}
                    </ul>
                  ))}
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-black/50">* 为 AI 补充或目标内容，尚未核验。</p>
            <button className="btn-secondary mt-4" onClick={() => regenerate.mutate({ scope: 'all' })}>整份重生成</button>
          </div>
        )}
      </section>

      <section className="card mt-6">
        <h2 className="text-2xl font-bold">导出简历</h2>
        {versionId && (status === 'ready' || status === 'degraded') ? (
          <div className="mt-4 flex flex-wrap gap-3">
            <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-preview`} target="_blank" rel="noreferrer">预览 HTML</a>
            <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-download?format=html`}>下载 HTML</a>
            <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-download?format=docx`}>下载 DOCX</a>
            <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-download?format=pdf`}>下载 PDF</a>
          </div>
        ) : <p className="mt-3 text-sm text-black/50">生成后可直接导出，不需要顾问批准。</p>}
      </section>

      <section className="card mt-6">
        <h2 className="text-2xl font-bold">准备面试</h2>
        {bundle.data?.guides && Object.keys(bundle.data.guides).length ? (
          <div className="mt-4 flex flex-wrap gap-3">
            {Object.entries(bundle.data.guides).map(([guideKind, guide]) => (
              <div key={guideKind} className="flex items-center gap-2">
                <a className="btn-secondary" href={`/app/guides?guide=${guide.id}`}>{guideKind === 'target' ? '蓝图风险指南' : '求职版作战指南'}</a>
                {guide.status === 'stale' && (
                  <button className="text-xs underline" onClick={() => regenerateGuide.mutate(guide.id)}>重新生成指南</button>
                )}
              </div>
            ))}
          </div>
        ) : <Empty title="简历包完成后会生成两份指南。" />}
      </section>
    </>
  )
}
