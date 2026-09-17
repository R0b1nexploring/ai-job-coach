import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'
import { Alert, Icon, PageHeader, StatusChip } from '../components/ui'
import {
  A4Preview,
  PreviewPlaceholder,
  StudioPanel,
  StudioWorkspace,
  type TaskStatus,
  type WorkspaceStep,
  type WorkspaceStepItem,
} from '../components/studio'
import type { ExperienceEntry, Job, ListResponse, Resume } from '../types'

type Profile = {
  id: string
  title: string
  mode: string
  job_ids?: string[]
  snapshot_json: { requirements?: Array<{ id: string; text: string; priority: string }> }
}

type StudioJob = Job & { raw_jd?: string }

const qualityStatusLabels: Record<string, string> = {
  passed: '已通过',
  ready: '已通过',
  degraded: '降级可用',
  failed: '未通过',
  pending: '检查中',
}

function qualityStatusLabel(status?: string) {
  if (!status) return '待检查'
  return qualityStatusLabels[status] || status
}

function SourceReferences({ ids }: { ids?: string[] }) {
  if (!ids?.length) return null
  return (
    <details className="mt-2 w-full">
      <summary className="inline-flex rounded-lg bg-ink/[0.035] px-2 py-1 text-xs text-ink-muted">
        已关联 {ids.length} 条素材事实
      </summary>
      <ul className="mt-2 space-y-1 rounded-lg bg-ink/[0.025] px-3 py-2 font-mono text-[10px] leading-4 text-ink-muted">
        {ids.map((id) => <li className="break-all" key={id}>{id}</li>)}
      </ul>
    </details>
  )
}
type Bundle = {
  id: string
  status: string
  error?: string
  can_retry?: boolean
  versions: Record<string, { id: string; kind: string; status: string; content_hash: string }>
  guides: Record<string, { id: string; status: string }>
  run?: { phase?: string; attempts?: number; max_attempts?: number; last_error?: string }
  generation_metadata_json?: {
    degraded?: boolean
    degraded_reason?: string
    quality_gate_bypassed?: boolean
    writer?: Record<string, string>
  }
}
type ResumeFact = {
  id: string
  label?: string
  value_json?: { text?: string; [key: string]: unknown }
  verification_status?: string
  organization?: string
  role_title?: string
  material_id?: string
  claim_type?: string
}
type MaterialDraft = {
  organization: string
  role_title: string
  summary: string
  skills: string
  details: Record<string, string>
}
type StudioBullet = {
  id: string
  text: string
  achieved?: boolean
  locked?: boolean
  source_fact_ids?: string[]
  source_target_ids?: string[]
  requirement_ids?: string[]
  verification_status?: string
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
    dimensions?: Record<string, { score: number | null; assessed?: boolean }>
    recommendations?: Array<{ bullet_id?: string; suggestion: string }>
  }
  content_json: {
    kind?: string
    factuality_policy?: string
    headline?: string
    sections?: Array<{
      name: string
      items: Array<{
        organization?: string
        role_title?: string
        bullets?: StudioBullet[]
      }>
    }>
  }
}

const A4_PREVIEW_WIDTH = 794
const A4_PREVIEW_HEIGHT = 1123

export function a4PreviewScale(containerWidth: number) {
  if (!Number.isFinite(containerWidth) || containerWidth <= 0) return 1
  return Math.min(1, Math.max(0.1, containerWidth / A4_PREVIEW_WIDTH))
}

export function bundleStageLabel(phase?: string) {
  return ({
    queued: '等待处理',
    writing: '正在组织内容',
    quality_check: '正在质量检查',
    layout: '正在排版',
    guides: '正在生成指南',
    completed: '已完成',
    failed: '处理失败',
  } as Record<string, string>)[phase || ''] || '处理中'
}

function showsBlueprintMark(content: StudioVersion['content_json'] | undefined, bullet: StudioBullet) {
  if (!bullet || bullet.achieved !== false) return false
  return !(
    content?.factuality_policy === 'ai_expansion'
    && bullet.verification_status === 'ai_generated'
    && !bullet.source_target_ids?.length
    && !bullet.requirement_ids?.length
  )
}

function materialDraft(entry: ExperienceEntry): MaterialDraft {
  return {
    organization: entry.organization || '',
    role_title: entry.role_title || '',
    summary: entry.summary || '',
    skills: (entry.skills_json || []).join('、'),
    details: {
      ...(entry.details_json || {}),
      project_type: entry.details_json?.project_type || '课程设计',
      actions: entry.details_json?.actions || entry.summary || '',
      tools: entry.details_json?.tools || (entry.skills_json || []).join('、'),
      results: entry.details_json?.results || '',
      ownership: entry.details_json?.ownership || '',
    },
  }
}

function WorkspaceJobContext({
  job,
  isLoading,
  profileReady,
  profileTitle,
}: {
  job?: StudioJob
  isLoading: boolean
  profileReady: boolean
  profileTitle?: string
}) {
  return (
    <div className="studio-context-stack">
      <section className="studio-context-card" aria-labelledby="workspace-jd-heading">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="studio-context-icon"><Icon name="target" className="h-4 w-4" /></span>
            <div className="min-w-0">
              <p className="eyebrow text-sage">目标岗位</p>
              <h2 id="workspace-jd-heading" className="mt-1 text-base font-semibold tracking-tight">目标 JD</h2>
            </div>
          </div>
          {profileReady && <StatusChip tone="success">已关联</StatusChip>}
        </div>

        {isLoading ? (
          <div className="mt-4 space-y-2" aria-label="正在加载目标 JD">
            <div className="skeleton h-4 w-3/4" />
            <div className="skeleton h-3 w-1/2" />
            <div className="skeleton h-20 w-full" />
          </div>
        ) : job ? (
          <>
            <div className="mt-4 rounded-xl border border-line bg-ink/[0.02] px-3 py-2.5">
              <p className="truncate text-sm font-semibold">{job.title || profileTitle || '已保存目标岗位'}</p>
              <p className="mt-1 truncate text-xs text-ink-secondary">{[job.company_name, job.city].filter(Boolean).join(' · ') || '岗位信息'}</p>
            </div>
            {job.raw_jd && <p className="studio-jd-excerpt mt-3">{job.raw_jd.slice(0, 118)}{job.raw_jd.length > 118 ? '…' : ''}</p>}
            <details className="studio-jd-details mt-3">
              <summary>查看 JD 原文</summary>
              {job.raw_jd ? <div className="studio-jd-body mt-2">{job.raw_jd}</div> : <p className="mt-2 text-xs text-ink-muted">原文正在同步，稍后刷新即可查看。</p>}
            </details>
            {job.source_url && (
              <a className="btn-secondary mt-3 w-full" href={job.source_url} target="_blank" rel="noreferrer">打开岗位来源<Icon name="chevron-right" /></a>
            )}
          </>
        ) : (
          <p className="mt-4 rounded-xl border border-dashed border-line bg-ink/[0.018] px-3 py-4 text-sm leading-6 text-ink-secondary">
            {profileReady ? '已保存岗位，完成同步后 JD 原文会显示在这里。' : '分析岗位后，保存的 JD 会固定在这里。'}
          </p>
        )}
      </section>

      <section className="studio-context-card" aria-labelledby="workspace-application-heading">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="studio-context-icon"><Icon name="delivery" className="h-4 w-4" /></span>
            <h2 id="workspace-application-heading" className="text-base font-semibold tracking-tight">投递入口</h2>
          </div>
          <StatusChip>待接入</StatusChip>
        </div>
        <p className="mt-3 text-xs leading-5 text-ink-secondary">接入投递数据库后，可从这里打开投递页面并回写进度。</p>
        <button type="button" className="btn-secondary mt-3 w-full" disabled aria-label="投递入口（即将接入）">
          投递入口（即将接入）<Icon name="chevron-right" />
        </button>
      </section>
    </div>
  )
}

export function ResumeStudio() {
  const client = useQueryClient()
  const [jdText, setJdText] = useState('')
  const [jobIds, setJobIds] = useState<string[]>([])
  const [selectedProfile, setSelectedProfile] = useState('')
  const [selectedResume, setSelectedResume] = useState('')
  const [bundleId, setBundleId] = useState('')
  const [kind, setKind] = useState<'submittable' | 'target'>('submittable')
  const [showCompare, setShowCompare] = useState(false)
  const [previousContent, setPreviousContent] = useState<StudioVersion['content_json'] | null>(null)
  const [message, setMessage] = useState('')
  const [showExperienceForm, setShowExperienceForm] = useState(false)
  const [experienceOrganization, setExperienceOrganization] = useState('')
  const [experienceProjectType, setExperienceProjectType] = useState('课程设计')
  const [experienceRole, setExperienceRole] = useState('')
  const [experienceText, setExperienceText] = useState('')
  const [experienceTools, setExperienceTools] = useState('')
  const [experienceResult, setExperienceResult] = useState('')
  const [pageVisible, setPageVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden')
  const [pollDelay, setPollDelay] = useState(2000)
  const [factDrafts, setFactDrafts] = useState<Record<string, string>>({})
  const [clarificationDrafts, setClarificationDrafts] = useState<Record<string, string>>({})
  const [materialDrafts, setMaterialDrafts] = useState<Record<string, MaterialDraft>>({})
  const [previewScale, setPreviewScale] = useState(1)
  const [activeStep, setActiveStep] = useState<WorkspaceStep>('target')
  const [stepInitialized, setStepInitialized] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const previewContainerRef = useRef<HTMLDivElement>(null)
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api<ListResponse<Job>>('/api/jobs') })
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: () => api<ListResponse<Resume>>('/api/resumes') })
  const selectedResumeDetail = useQuery({
    queryKey: ['resume-detail', selectedResume],
    queryFn: () => api<Resume & { missing_information_json?: Array<{ fact_id: string; field: string; question: string }> }>(`/api/resumes/${selectedResume}`),
    enabled: Boolean(selectedResume),
  })
  const resumeFacts = useQuery({
    queryKey: ['resume-facts', selectedResume],
    queryFn: () => api<ListResponse<ResumeFact>>(`/api/resumes/${selectedResume}/facts`),
    enabled: Boolean(selectedResume),
  })
  const materials = useQuery({ queryKey: ['experience'], queryFn: () => api<ListResponse<ExperienceEntry>>('/api/experience') })
  const materialFacts = useQuery({ queryKey: ['experience-facts'], queryFn: () => api<ListResponse<ResumeFact>>('/api/experience-facts') })
  const profiles = useQuery({ queryKey: ['target-profiles'], queryFn: () => api<ListResponse<Profile>>('/api/target-profiles') })
  const activeProfile = useMemo(
    () => (profiles.data?.items || []).find((profile) => profile.id === selectedProfile),
    [profiles.data?.items, selectedProfile],
  )
  const selectedJobId = activeProfile?.job_ids?.[0] || (activeProfile ? jobIds[0] : '')
  const selectedJob = useQuery({
    queryKey: ['workspace-job', selectedJobId],
    queryFn: () => api<StudioJob>(`/api/jobs/${selectedJobId}`),
    enabled: Boolean(selectedJobId),
  })
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
      return pageVisible && (status === 'queued' || status === 'generating') ? pollDelay : false
    },
    refetchOnWindowFocus: true,
  })
  useEffect(() => {
    if (typeof document === 'undefined') return
    const updateVisibility = () => setPageVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', updateVisibility)
    return () => document.removeEventListener('visibilitychange', updateVisibility)
  }, [])
  useEffect(() => {
    const pending = bundle.data?.status === 'queued' || bundle.data?.status === 'generating'
    if (!pending) {
      setPollDelay(2000)
      return
    }
    if (bundle.dataUpdatedAt) setPollDelay((current) => Math.min(current === 2000 ? 2500 : current + 1000, 5000))
  }, [bundle.dataUpdatedAt, bundle.data?.status])
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
  useEffect(() => {
    if (stepInitialized || profiles.isLoading || bundles.isLoading) return
    const latest = bundles.data?.items?.[0]
    if (latest && (latest.status === 'ready' || latest.status === 'degraded')) setActiveStep('resume')
    else if (profiles.data?.items?.length) setActiveStep('materials')
    else setActiveStep('target')
    setStepInitialized(true)
  }, [bundles.data?.items, bundles.isLoading, profiles.data?.items, profiles.isLoading, stepInitialized])

  useEffect(() => {
    if (!resumeFacts.data?.items) return
    setFactDrafts((current) => {
      const next = { ...current }
      for (const fact of resumeFacts.data.items) {
        if (!(fact.id in next)) next[fact.id] = fact.value_json?.text || ''
      }
      return next
    })
  }, [resumeFacts.data])
  useEffect(() => {
    const own = (materials.data?.items || []).filter((item) => item.is_own)
    if (!own.length) return
    setMaterialDrafts((current) => {
      const next = { ...current }
      for (const item of own) {
        if (!next[item.id]) next[item.id] = materialDraft(item)
      }
      return next
    })
  }, [materials.data?.items])
  const versionId = bundle.data?.versions?.[kind]?.id || ''
  const version = useQuery({
    queryKey: ['studio-version', versionId],
    queryFn: () => api<StudioVersion>(`/api/resume-versions/${versionId}/studio`),
    enabled: Boolean(versionId),
  })
  // On a narrow screen the preview is a full-screen drawer. Open it when a
  // deliverable first becomes available so the generated result is immediately
  // visible without requiring a second tap; closing it remains user-controlled.
  useEffect(() => {
    if (typeof window === 'undefined' || !version.data) return
    if (window.innerWidth < 768) setPreviewOpen(true)
  }, [version.data?.id])
  useEffect(() => {
    const container = previewContainerRef.current
    if (!container) return
    const updateScale = () => {
      // A grid/card may retain a desktop min-content width while its viewport
      // is already narrow.  Cap by the visible viewport as well, so the A4
      // canvas cannot remain 794px wide on a phone.
      const viewportWidth = Math.max(0, window.innerWidth - 48)
      setPreviewScale(a4PreviewScale(Math.min(container.clientWidth, viewportWidth)))
    }
    updateScale()
    window.addEventListener('resize', updateScale)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateScale)
    observer?.observe(container)
    return () => {
      window.removeEventListener('resize', updateScale)
      observer?.disconnect()
    }
  }, [version.data?.content_hash, previewOpen])
  const compareKind = kind === 'submittable' ? 'target' : 'submittable'
  const compareVersionId = bundle.data?.versions?.[compareKind]?.id || ''
  const compareVersion = useQuery({
    queryKey: ['studio-version', compareVersionId],
    queryFn: () => api<StudioVersion>(`/api/resume-versions/${compareVersionId}/studio`),
    enabled: showCompare && Boolean(compareVersionId),
  })
  const analyzeTarget = useMutation({
    mutationFn: async (raw: string) => {
      const job = await api<Job>('/api/jobs/import-text', {
        method: 'POST',
        // Let the server extract only identities that occur in the pasted JD.
        // Supplying generic labels here used to turn them into fake job facts.
        body: JSON.stringify({ raw_jd: raw }),
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
      setActiveStep('materials')
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
      setActiveStep('materials')
      setMessage('目标画像已创建。')
      client.invalidateQueries({ queryKey: ['target-profiles'] })
    },
  })
  const createMaterial = useMutation({
    mutationFn: async () => {
      return api<ExperienceEntry>('/api/experience', {
        method: 'POST',
        body: JSON.stringify({
          kind: 'project',
          title: experienceText.trim().slice(0, 40) || '补充经历',
          organization: experienceOrganization.trim(),
          role_title: experienceRole.trim(),
          summary: experienceText.trim(),
          skills_json: experienceTools.split(/[，,、]/).map((item) => item.trim()).filter(Boolean),
          details_json: {
            project_type: experienceProjectType,
            actions: experienceText.trim(),
            tools: experienceTools.trim(),
            results: experienceResult.trim(),
          },
        }),
      })
    },
    onSuccess: (row) => {
      setMaterialDrafts((current) => ({ ...current, [row.id]: materialDraft(row) }))
      setExperienceOrganization('')
      setExperienceProjectType('课程设计')
      setExperienceRole('')
      setExperienceText('')
      setExperienceTools('')
      setExperienceResult('')
      setShowExperienceForm(false)
      setMessage('空白素材已保存。你可以继续编辑、查看缺口并确认原子事实，也可以先用草稿生成。')
      client.invalidateQueries({ queryKey: ['experience'] })
    },
  })
  const saveMaterial = useMutation({
    mutationFn: ({ item, draft }: { item: ExperienceEntry; draft: MaterialDraft }) => api<ExperienceEntry>(`/api/experience/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        organization: draft.organization,
        role_title: draft.role_title,
        summary: draft.summary,
        skills_json: (draft.details.tools || draft.skills).split(/[，,、]/).map((value) => value.trim()).filter(Boolean),
        details_json: { ...draft.details, actions: draft.summary, tools: draft.details.tools || draft.skills },
      }),
    }),
    onSuccess: (row) => {
      setMaterialDrafts((current) => ({ ...current, [row.id]: materialDraft(row) }))
      setMessage('素材修改已保存；如曾确认，相关事实已恢复为待确认。')
      client.invalidateQueries({ queryKey: ['experience'] })
      client.invalidateQueries({ queryKey: ['experience-facts'] })
      client.invalidateQueries({ queryKey: ['resume-bundles'] })
    },
  })
  const clarifyMaterial = useMutation({
    mutationFn: (entryId: string) => api<ExperienceEntry>(`/api/experience/${entryId}/clarifications`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('缺口追问已生成；不知道的内容可以留空，不需要猜。')
      client.invalidateQueries({ queryKey: ['experience'] })
    },
  })
  const confirmMaterial = useMutation({
    mutationFn: (entryId: string) => api<ExperienceEntry>(`/api/experience/${entryId}/confirm`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('素材已拆成原子事实并确认。')
      client.invalidateQueries({ queryKey: ['experience'] })
      client.invalidateQueries({ queryKey: ['experience-facts'] })
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
  const editFact = useMutation({
    mutationFn: (payload: { fact: ResumeFact; text: string }) => api(`/api/resume-facts/${payload.fact.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ value_json: { ...(payload.fact.value_json || {}), text: payload.text } }),
    }),
    onSuccess: () => {
      setMessage('原子事实已保存，仍需重新确认。')
      client.invalidateQueries({ queryKey: ['resume-facts', selectedResume] })
      client.invalidateQueries({ queryKey: ['resume-detail', selectedResume] })
    },
  })
  const confirmFact = useMutation({
    mutationFn: (factId: string) => api(`/api/resume-facts/${factId}/confirm`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('这条原子事实已确认。')
      client.invalidateQueries({ queryKey: ['resume-facts', selectedResume] })
      client.invalidateQueries({ queryKey: ['resume-detail', selectedResume] })
      client.invalidateQueries({ queryKey: ['resumes'] })
    },
  })
  const answerClarifications = useMutation({
    mutationFn: () => api(`/api/resumes/${selectedResume}/answer-clarifications`, {
      method: 'POST',
      body: JSON.stringify((selectedResumeDetail.data?.missing_information_json || []).map((item) => ({
        fact_id: item.fact_id,
        field: item.field,
        value: clarificationDrafts[`${item.fact_id}:${item.field}`] || '',
      })).filter((item) => item.value.trim())),
    }),
    onSuccess: () => {
      setMessage('补充信息已保存，请重新确认事实。')
      setClarificationDrafts({})
      client.invalidateQueries({ queryKey: ['resume-facts', selectedResume] })
      client.invalidateQueries({ queryKey: ['resume-detail', selectedResume] })
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
      setActiveStep('resume')
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
    mutationFn: (payload: { bulletId: string; locked: boolean }) => api(`/api/resume-versions/${versionId}/lock`, { method: 'POST', body: JSON.stringify({ bullet_id: payload.bulletId, locked: payload.locked }) }),
    onMutate: () => { if (version.data) setPreviousContent(version.data.content_json) },
    onSuccess: () => {
      setMessage('锁定状态已保存并重新校验。')
      client.invalidateQueries({ queryKey: ['studio-version', versionId] })
      client.invalidateQueries({ queryKey: ['resume-bundle', bundleId] })
    },
  })
  const regenerate = useMutation({
    mutationFn: (payload: { scope: 'all' | 'bullet' | 'section'; bullet_id?: string; section_name?: string }) => api(`/api/resume-versions/${versionId}/regenerate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
    onSuccess: () => {
      setMessage('已重生成并重新校验。')
      client.invalidateQueries({ queryKey: ['studio-version', versionId] })
      client.invalidateQueries({ queryKey: ['resume-bundle', bundleId] })
    },
    onMutate: () => { if (version.data) setPreviousContent(version.data.content_json) },
  })
  const reorder = useMutation({
    mutationFn: (payload: { bullet_id: string; direction: 'up' | 'down' }) => api(`/api/resume-versions/${versionId}/reorder`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
    onMutate: () => { if (version.data) setPreviousContent(version.data.content_json) },
    onSuccess: () => {
      setMessage('顺序已保存并重新校验。')
      client.invalidateQueries({ queryKey: ['studio-version', versionId] })
      client.invalidateQueries({ queryKey: ['resume-bundle', bundleId] })
    },
  })
  const undo = useMutation({
    mutationFn: () => api(`/api/resume-versions/${versionId}`, {
      method: 'PATCH',
      body: JSON.stringify(previousContent),
    }),
    onSuccess: () => {
      setPreviousContent(null)
      setMessage('已撤销上一次工作台操作，并重新校验。')
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

  const changeMaterialDraft = (entry: ExperienceEntry, field: string, value: string) => {
    setMaterialDrafts((current) => {
      const draft = current[entry.id] || materialDraft(entry)
      if (field.startsWith('details.')) {
        return {
          ...current,
          [entry.id]: {
            ...draft,
            details: { ...draft.details, [field.slice('details.'.length)]: value },
          },
        }
      }
      return { ...current, [entry.id]: { ...draft, [field]: value } }
    })
  }

  if (jobs.isLoading || resumes.isLoading) return <Loading />
  const error = jobs.error || resumes.error || selectedResumeDetail.error || resumeFacts.error || materialFacts.error || generate.error || createProfile.error || analyzeTarget.error || createMaterial.error || saveMaterial.error || clarifyMaterial.error || confirmMaterial.error || uploadResume.error || confirmResume.error || editFact.error || confirmFact.error || answerClarifications.error || retry.error || lock.error || regenerate.error || reorder.error || undo.error || regenerateGuide.error
  const status = bundle.data?.status
  const degraded = status === 'degraded'
  const qualityGateBypassed = bundle.data?.generation_metadata_json?.quality_gate_bypassed === true
  const failed = status === 'failed'
  const pending = status === 'queued' || status === 'generating'
  const content = version.data?.content_json
  const reviewerNote = version.data?.quality_report_json.reviewer_note
  const deliverable = Boolean(versionId && (status === 'ready' || status === 'degraded'))
  const stepStatus = (step: WorkspaceStep, complete: boolean, available: boolean): TaskStatus => {
    if (activeStep === step) return 'current'
    if (complete) return 'complete'
    return available ? 'available' : 'blocked'
  }
  const workspaceSteps: WorkspaceStepItem[] = [
    { id: 'target', label: '岗位', description: '理解目标要求', status: stepStatus('target', Boolean(selectedProfile), true) },
    { id: 'materials', label: '素材', description: '补充个人经历', status: stepStatus('materials', Boolean(selectedResume || ownMaterials.length), Boolean(selectedProfile)) },
    { id: 'resume', label: '双版简历', description: '生成与调整', status: stepStatus('resume', deliverable, Boolean(selectedProfile)) },
    { id: 'delivery', label: '导出与指南', description: '下载交付物', status: stepStatus('delivery', deliverable && Boolean(Object.keys(bundle.data?.guides || {}).length), deliverable) },
  ]
  const previewPane = version.data ? (
    <A4Preview
      containerRef={previewContainerRef}
      versionId={versionId}
      contentHash={version.data.content_hash}
      scale={previewScale}
      width={A4_PREVIEW_WIDTH}
      height={A4_PREVIEW_HEIGHT}
      showHeader={!previewOpen}
    />
  ) : <PreviewPlaceholder profileReady={Boolean(selectedProfile)} materialCount={ownMaterials.length + (selectedResume ? 1 : 0)} />
  return (
    <>
      <PageHeader
        kicker="简历工作台"
        title="一份求职简历，一份蓝图 Plus"
        lead="围绕一个目标岗位，整理素材、生成双版本并完成导出。"
        extra={
          <div className="flex flex-wrap items-center gap-2">
            {selectedProfile ? <StatusChip tone="success"><span className="h-1.5 w-1.5 rounded-full bg-current" />目标已就绪</StatusChip> : <StatusChip>尚未分析岗位</StatusChip>}
            <a href="/app/history" className="btn-secondary"><Icon name="history" className="h-4 w-4" />生成记录</a>
          </div>
        }
      />
      {(error || message || degraded || qualityGateBypassed || failed || pending) && (
        <div className="mt-5 space-y-3">
          {error && <ErrorState error={error} />}
          {message && <Alert tone="success">{message}</Alert>}
          {degraded && <Alert tone="warning" role="status">当前为降级版本：{bundle.data?.generation_metadata_json?.degraded_reason || '模型不可用，使用已通过硬门禁的本地基础内容。'}</Alert>}
          {qualityGateBypassed && <Alert tone="warning" role="status">本地调试模式：质量硬门禁已暂时关闭，仅保留事实来源检查。</Alert>}
          {failed && (
            <Alert tone="danger" role="alert">
              生成失败：{bundle.data?.error || '请重试。'}
            </Alert>
          )}
          {pending && (
            <Alert tone="info">
              <span className="mr-2 inline-flex align-middle"><span className="spinner text-sage" /></span>
              状态：{status === 'queued' ? '排队中' : '生成中'}（{bundleStageLabel(bundle.data?.run?.phase)}），完成后会自动刷新。
            </Alert>
          )}
        </div>
      )}

      <StudioWorkspace
        steps={workspaceSteps}
        activeStep={activeStep}
        onStepChange={setActiveStep}
        preview={previewPane}
        previewOpen={previewOpen}
        onPreviewOpen={() => setPreviewOpen(true)}
        onPreviewClose={() => setPreviewOpen(false)}
        context={<WorkspaceJobContext job={selectedJob.data} isLoading={selectedJob.isLoading} profileReady={Boolean(selectedProfile)} profileTitle={activeProfile?.title} />}
      >
      {activeStep === 'target' && (
      <StudioPanel
        eyebrow="01 · 目标岗位"
        title="你想申请什么岗位？"
        description="复制招聘页面里的职位描述，系统会保存原文并建立可追溯的目标画像。"
        status={selectedProfile ? <StatusChip tone="success">已分析</StatusChip> : undefined}
      >
        <textarea
          className="field mt-4 min-h-28"
          name="jd-raw"
          placeholder="在这里粘贴职位描述（JD）…"
          value={jdText}
          onChange={(event) => setJdText(event.target.value)}
        />
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn" onClick={() => jdText && analyzeTarget.mutate(jdText)} disabled={!jdText.trim() || analyzeTarget.isPending}>
            {analyzeTarget.isPending ? '正在分析…' : '分析这个岗位'}
          </button>
        </div>
        {(profiles.data?.items || []).length > 0 && (
          <details className="mt-5 rounded-xl border border-line bg-ink/[0.02] p-3">
            <summary className="cursor-pointer text-sm font-semibold">使用之前分析过的岗位</summary>
            <select className="field mt-3" aria-label="已有岗位目标" value={selectedProfile} onChange={(event) => setSelectedProfile(event.target.value)}>
              {(profiles.data?.items || []).map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.title}</option>
              ))}
            </select>
          </details>
        )}
        {(jobs.data?.items || []).length >= 2 && (
          <details className="mt-3 rounded-xl border border-line p-3">
            <summary className="cursor-pointer text-sm text-ink-secondary">高级：合并多个已有岗位</summary>
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
      </StudioPanel>
      )}

      {activeStep === 'materials' && (
      <StudioPanel
        eyebrow="02 · 个人素材"
        title="让结果更像你"
        description="上传现有简历，或补充一段经历；没有素材也可以直接生成。"
        status={ownMaterials.length || selectedResume ? <StatusChip tone="success">{ownMaterials.length + (selectedResume ? 1 : 0)} 项素材</StatusChip> : <StatusChip>可选</StatusChip>}
        actions={<button className="btn" disabled={!selectedProfile || generate.isPending} onClick={() => generate.mutate()}>生成求职版和蓝图 Plus<Icon name="chevron-right" /></button>}
      >
        <div className="flex flex-wrap gap-2">
          <label className="btn-secondary cursor-pointer">
            <Icon name="upload" />上传现有简历
            <input className="hidden" type="file" accept=".docx,.pdf" onChange={(event) => event.target.files?.[0] && uploadResume.mutate(event.target.files[0])} />
          </label>
          <button className="btn-secondary" onClick={() => setShowExperienceForm((current) => !current)}>
            <Icon name={showExperienceForm ? 'close' : 'plus'} />{showExperienceForm ? '收起' : '补充一段经历'}
          </button>
        </div>
        {showExperienceForm && (
          <div className="mt-4 rounded-xl border border-sage/30 bg-sage/5 p-4">
            <label className="block text-sm font-semibold" htmlFor="experience-project-type">项目类型</label>
            <select id="experience-project-type" className="field mt-1" value={experienceProjectType} onChange={(event) => setExperienceProjectType(event.target.value)}>
              <option>课程设计</option>
              <option>个人项目</option>
              <option>科研项目</option>
              <option>竞赛项目</option>
              <option>实习项目</option>
            </select>
            <label className="block text-sm font-semibold">在哪里完成的？</label>
            <input className="field mt-1" value={experienceOrganization} onChange={(event) => setExperienceOrganization(event.target.value)} placeholder="例如：学校实验室、某公司或个人项目" />
            <label className="mt-4 block text-sm font-semibold">你的角色 <span className="font-normal text-ink-muted">选填</span></label>
            <input className="field mt-1" value={experienceRole} onChange={(event) => setExperienceRole(event.target.value)} placeholder="例如：结构设计负责人、项目成员" />
            <label className="mt-4 block text-sm font-semibold">你具体做了什么？</label>
            <textarea className="field mt-1 min-h-24" value={experienceText} onChange={(event) => setExperienceText(event.target.value)} placeholder="用自己的话描述即可，例如：我用 SolidWorks 完成了装配体建模和工程图。" />
            <label className="mt-4 block text-sm font-semibold">实际使用的工具 <span className="font-normal text-ink-muted">选填</span></label>
            <input className="field mt-1" value={experienceTools} onChange={(event) => setExperienceTools(event.target.value)} placeholder="例如：SolidWorks、Excel、Python" />
            <label className="mt-4 block text-sm font-semibold">有什么结果？ <span className="font-normal text-ink-muted">选填</span></label>
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
        {selectedResume && (
          <div className="mt-5 rounded-xl border border-line bg-ink/[0.02] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="font-semibold">核对这份简历的原子事实</h3>
                <p className="mt-1 text-sm text-ink-secondary">只确认你本人能核验的内容；AI 不会替你补数字。</p>
              </div>
              <button type="button" className="btn-secondary" onClick={() => confirmResume.mutate(selectedResume)} disabled={confirmResume.isPending}>确认全部事实</button>
            </div>
            {(resumeFacts.data?.items || []).length > 0 ? (
              <div className="mt-3 grid gap-3">
                {(resumeFacts.data?.items || []).map((fact) => (
                  <div className="rounded-2xl border border-line bg-white p-3" key={fact.id}>
                    <p className="text-xs text-ink-muted">{fact.label || fact.role_title || '事实'} · {fact.verification_status === 'user_confirmed' ? '已确认' : '待确认'}</p>
                    <textarea
                      className="field mt-2 min-h-16"
                      aria-label={`事实 ${fact.label || fact.id}`}
                      value={factDrafts[fact.id] ?? fact.value_json?.text ?? ''}
                      onChange={(event) => setFactDrafts((current) => ({ ...current, [fact.id]: event.target.value }))}
                    />
                    <div className="mt-2 flex gap-3 text-xs">
                      <button type="button" className="underline" onClick={() => editFact.mutate({ fact, text: factDrafts[fact.id] ?? fact.value_json?.text ?? '' })} disabled={editFact.isPending}>保存事实</button>
                      {fact.verification_status !== 'user_confirmed' && <button type="button" className="underline" onClick={() => confirmFact.mutate(fact.id)} disabled={confirmFact.isPending}>确认这条</button>}
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="mt-3 text-sm text-ink-secondary">这份简历还没有解析出事实，可以直接补充一段经历。</p>}
            {(selectedResumeDetail.data?.missing_information_json || []).length > 0 && (
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
                <h4 className="font-semibold text-amber-900">还需要补充</h4>
                <div className="mt-2 grid gap-2">
                  {(selectedResumeDetail.data?.missing_information_json || []).map((item) => {
                    const key = `${item.fact_id}:${item.field}`
                    return (
                      <label className="text-sm text-amber-900" key={key}>
                        {item.question}
                        <input className="field mt-1 bg-white" value={clarificationDrafts[key] || ''} onChange={(event) => setClarificationDrafts((current) => ({ ...current, [key]: event.target.value }))} />
                      </label>
                    )
                  })}
                </div>
                <button type="button" className="btn-secondary mt-3" onClick={() => answerClarifications.mutate()} disabled={answerClarifications.isPending}>保存补充信息</button>
              </div>
            )}
          </div>
        )}
        {ownMaterials.length > 0 && (
          <div className="mt-5">
            <h3 className="font-semibold">已保存的经历与素材（{ownMaterials.length}）</h3>
            <p className="mt-1 text-sm text-ink-secondary">空白建档的素材可以在这里反复修改、补齐追问并确认，不需要跳到旧页面。</p>
            <div className="mt-3 grid gap-3">
              {ownMaterials.map((item) => {
                const draft = materialDrafts[item.id] || materialDraft(item)
                const facts = (materialFacts.data?.items || []).filter((fact) => fact.material_id === item.id && fact.verification_status !== 'user_rejected')
                return (
                  <details className="rounded-2xl border border-line bg-ink/[0.02] p-4" key={item.id} open={item.status === 'draft'}>
                    <summary className="cursor-pointer font-semibold">
                      {item.title} · {item.status === 'confirmed' ? '已确认' : '待确认'}
                    </summary>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <label className="text-sm font-semibold">
                        组织或场景
                        <input className="field mt-1" aria-label={`${item.title} 组织`} value={draft.organization} onChange={(event) => changeMaterialDraft(item, 'organization', event.target.value)} />
                      </label>
                      <label className="text-sm font-semibold">
                        你的角色
                        <input className="field mt-1" aria-label={`${item.title} 角色`} value={draft.role_title} onChange={(event) => changeMaterialDraft(item, 'role_title', event.target.value)} />
                      </label>
                      <label className="text-sm font-semibold md:col-span-2">
                        你具体做了什么
                        <textarea className="field mt-1 min-h-20" aria-label={`${item.title} 行动`} value={draft.summary} onChange={(event) => changeMaterialDraft(item, 'summary', event.target.value)} />
                      </label>
                      <label className="text-sm font-semibold">
                        实际使用的工具
                        <input className="field mt-1" aria-label={`${item.title} 工具`} value={draft.details.tools || draft.skills} onChange={(event) => changeMaterialDraft(item, 'details.tools', event.target.value)} />
                      </label>
                      <label className="text-sm font-semibold">
                        可核验结果
                        <input className="field mt-1" aria-label={`${item.title} 结果`} value={draft.details.results || ''} onChange={(event) => changeMaterialDraft(item, 'details.results', event.target.value)} />
                      </label>
                      <label className="text-sm font-semibold md:col-span-2">
                        本人贡献边界
                        <input className="field mt-1" aria-label={`${item.title} 个人贡献`} value={draft.details.ownership || ''} onChange={(event) => changeMaterialDraft(item, 'details.ownership', event.target.value)} placeholder="例如：本人负责建模与工程图，测试由同组同学完成" />
                      </label>
                    </div>
                    {!!item.clarifications_json?.length && (
                      <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3">
                        <h4 className="font-semibold text-amber-900">缺口追问</h4>
                        <div className="mt-2 grid gap-2">
                          {item.clarifications_json.map((question) => (
                            <label className="text-sm text-amber-900" key={`${item.id}-${question.field}`}>
                              {question.question}
                              <input
                                className="field mt-1 bg-white"
                                aria-label={`${item.title} ${question.question}`}
                                value={draft.details[question.field] || ''}
                                onChange={(event) => changeMaterialDraft(item, `details.${question.field}`, event.target.value)}
                              />
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button type="button" className="btn-secondary" onClick={() => saveMaterial.mutate({ item, draft })} disabled={saveMaterial.isPending}>保存修改</button>
                      <button type="button" className="btn-secondary" onClick={() => clarifyMaterial.mutate(item.id)} disabled={clarifyMaterial.isPending}>查看缺口追问</button>
                      {item.status !== 'confirmed' && <button type="button" className="btn" onClick={() => confirmMaterial.mutate(item.id)} disabled={confirmMaterial.isPending}>确认并生成原子事实</button>}
                    </div>
                    {facts.length > 0 && (
                      <div className="mt-4 rounded-xl bg-white p-3">
                        <h4 className="text-sm font-semibold">已拆分的原子事实</h4>
                        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-secondary">
                          {facts.map((fact) => (
                            <li key={fact.id}>{fact.value_json?.text || fact.label} · {fact.verification_status === 'user_confirmed' ? '已确认' : '待确认'}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </details>
                )
              })}
            </div>
          </div>
        )}
      </StudioPanel>
      )}

      {activeStep === 'resume' && (
      <StudioPanel
        eyebrow="03 · 双版简历"
        title="生成与调整"
        description="在求职版和蓝图 Plus 之间切换，并对每个要点进行锁定、排序或局部重写。"
        status={pending ? <StatusChip tone="info">{bundleStageLabel(bundle.data?.run?.phase)}</StatusChip> : deliverable ? <StatusChip tone={degraded ? 'warning' : 'success'}>{degraded ? '降级可用' : '已通过'}</StatusChip> : undefined}
        actions={<>
          <button className="btn" disabled={!selectedProfile || generate.isPending} onClick={() => generate.mutate()}>{version.data ? '重新生成双版本' : '生成求职版和蓝图 Plus'}</button>
          {failed && bundle.data?.can_retry && (
            <button className="btn-secondary" onClick={() => retry.mutate()}>重试生成</button>
          )}
        </>}
      >
        {bundle.data && (
          <div className="segmented">
            <button className={`segmented-item ${kind === 'submittable' ? 'segmented-item-active' : ''}`} onClick={() => setKind('submittable')}>求职版</button>
            <button className={`segmented-item ${kind === 'target' ? 'segmented-item-active' : ''}`} onClick={() => setKind('target')}>蓝图 Plus</button>
          </div>
        )}
        {version.data && (
          <div className="mt-5">
            <div className="flex flex-wrap items-center gap-2 text-sm text-ink-secondary"><span>质量状态</span><StatusChip tone={version.data.quality_report_json.status === 'passed' ? 'success' : 'warning'}>{qualityStatusLabel(version.data.quality_report_json.status || version.data.guard_status)}</StatusChip>{reviewerNote && <span>{reviewerNote}</span>}</div>
            {!!version.data.quality_report_json.issues?.length && <p className="alert alert-warning mt-2">质量问题：{version.data.quality_report_json.issues.join('；')}</p>}
            {!!version.data.quality_report_json.recommendations?.length && (
              <div className="mt-2 rounded-lg bg-sage/5 px-3 py-2 text-sm text-ink-secondary">
                <p className="font-semibold">可改进之处</p>
                <ul className="mt-1 list-disc pl-5">
                  {version.data.quality_report_json.recommendations.map((item, index) => <li key={`${item.bullet_id || 'general'}-${index}`}>{item.suggestion}</li>)}
                </ul>
              </div>
            )}
            <div className="soft-panel mt-4" aria-label="编辑要点">
              <h3 className="text-sm font-semibold">编辑要点</h3>
              <p className="mt-1 text-xs text-ink-secondary">所有操作都会重新执行质量检查，并同步右侧 A4 预览。</p>
              {(content?.sections || []).map((section) => (
                <div key={section.name} className="mt-4 border-t border-line pt-3">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="font-semibold">{section.name}</h4>
                    <button className="btn-ghost" onClick={() => regenerate.mutate({ scope: 'section', section_name: section.name })}>重写此分区</button>
                  </div>
                  {section.items.map((item, itemIndex) => (
                    <ul key={`${section.name}-${itemIndex}`} className="mt-2 space-y-2">
                      {(item.bullets || []).map((bullet, bulletIndex) => (
                        <li key={bullet.id} className={`rounded-xl border bg-white px-3 py-3 ${bullet.locked ? 'border-sage/25' : 'border-line'}`}>
                          <p className="text-sm leading-6">
                            {bullet.text}{showsBlueprintMark(content, bullet) ? '*' : ''}
                          </p>
                          <SourceReferences ids={bullet.source_fact_ids} />
                          <div className="mt-2 flex flex-wrap items-center gap-1 border-t border-line pt-1.5">
                            <button className="btn-ghost" onClick={() => lock.mutate({ bulletId: bullet.id, locked: !bullet.locked })} disabled={lock.isPending}>{bullet.locked ? '解锁' : '锁定'}</button>
                            {!bullet.locked && (
                              <button className="btn-ghost" onClick={() => regenerate.mutate({ scope: 'bullet', bullet_id: bullet.id })}>重写本条</button>
                            )}
                            <button className="btn-ghost" onClick={() => reorder.mutate({ bullet_id: bullet.id, direction: 'up' })} disabled={bulletIndex === 0 || reorder.isPending}>上移</button>
                            <button className="btn-ghost" onClick={() => reorder.mutate({ bullet_id: bullet.id, direction: 'down' })} disabled={bulletIndex === (item.bullets || []).length - 1 || reorder.isPending}>下移</button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ))}
                </div>
              ))}
            </div>
            {(content?.sections || []).some((section) => section.items.some((item) => (item.bullets || []).some((bullet) => showsBlueprintMark(content, bullet)))) && (
              <p className="mt-3 text-xs text-ink-secondary">* 为目标蓝图未达成内容，尚未形成可核验经历。</p>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              <button className="btn-secondary" onClick={() => regenerate.mutate({ scope: 'all' })} disabled={regenerate.isPending}>{regenerate.isPending ? '正在重新校验…' : '整份重生成'}</button>
              <button className="btn-secondary" onClick={() => setShowCompare((current) => !current)}>{showCompare ? '收起版本对比' : '对比另一版'}</button>
              {previousContent && <button className="btn-secondary" onClick={() => undo.mutate()} disabled={undo.isPending}>撤销上次操作</button>}
            </div>
            {showCompare && compareVersion.data && (
              <div className="soft-panel mt-4" data-testid="version-compare">
                <h3 className="font-semibold">{compareKind === 'target' ? '蓝图 Plus' : '求职版'}对比</h3>
                {(compareVersion.data.content_json.sections || []).map((section) => (
                  <div className="mt-3" key={section.name}>
                    <h4 className="text-sm font-semibold">{section.name}</h4>
                      <ul className="list-disc pl-5 text-sm">
                        {section.items.flatMap((item) => (item.bullets || []).map((bullet) => <li key={bullet.id}>{bullet.text}{showsBlueprintMark(compareVersion.data.content_json, bullet) ? ' *' : ''}</li>))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </StudioPanel>
      )}

      {activeStep === 'delivery' && (
      <StudioPanel
        eyebrow="04 · 交付"
        title="导出与面试指南"
        description="所有文件都来自当前保存版本；PDF 故障不会影响其他格式和指南。"
        status={deliverable ? <StatusChip tone="success">可交付</StatusChip> : <StatusChip>等待简历生成</StatusChip>}
      >
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="soft-panel bg-white">
          <div className="flex items-center gap-2"><Icon name="download" className="h-5 w-5 text-sage" /><h2 className="section-heading">导出简历</h2></div>
          {versionId && (status === 'ready' || status === 'degraded') ? (
            <div className="mt-4 grid gap-2">
              <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-preview`} target="_blank" rel="noreferrer">预览 HTML</a>
              <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-download?format=html`}>下载 HTML</a>
              <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-download?format=docx`}>下载 DOCX</a>
              <a className="btn-secondary" href={`/api/resume-versions/${versionId}/studio-download?format=pdf`}>下载 PDF</a>
            </div>
          ) : <p className="mt-3 text-sm text-ink-secondary">生成后可直接导出，不需要顾问批准。</p>}
        </section>

        <section className="soft-panel bg-white">
          <div className="flex items-center gap-2"><Icon name="guides" className="h-5 w-5 text-sage" /><h2 className="section-heading">准备面试</h2></div>
          {bundle.data?.guides && Object.keys(bundle.data.guides).length ? (
            <div className="mt-4 grid gap-3">
              {Object.entries(bundle.data.guides).map(([guideKind, guide]) => (
                <div key={guideKind} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-white px-3.5 py-3">
                  <a className="flex items-center gap-1.5 font-semibold text-sage hover:underline" href={`/app/guides?guide=${guide.id}`}>{guideKind === 'target' ? '蓝图风险指南' : '求职版作战指南'}<Icon name="chevron-right" /></a>
                  {guide.status === 'stale' && (
                    <button className="btn-ghost" onClick={() => regenerateGuide.mutate(guide.id)}>重新生成指南</button>
                  )}
                </div>
              ))}
            </div>
          ) : <div className="mt-4"><Empty title="简历包完成后会生成两份指南。" /></div>}
        </section>
      </div>
      </StudioPanel>
      )}
      </StudioWorkspace>
    </>
  )
}
