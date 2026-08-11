import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'
import type { CapabilityTarget, Job, ListResponse } from '../types'

const severityLabels = { high: '高优先级', medium: '中优先级', low: '低优先级' }
const statusLabels = {
  pending: '待开始',
  in_progress: '学习中',
  achieved: '已达成',
  abandoned: '已放弃',
}

export function CapabilityTargets() {
  const client = useQueryClient()
  const [searchParams] = useSearchParams()
  const requestedJobId = searchParams.get('job_id') || ''
  const [evidenceTarget, setEvidenceTarget] = useState<CapabilityTarget | null>(null)
  const [evidence, setEvidence] = useState('')
  const [evidenceError, setEvidenceError] = useState('')
  const [message, setMessage] = useState('')
  const targets = useQuery({
    queryKey: ['capability-targets'],
    queryFn: () => api<ListResponse<CapabilityTarget>>('/api/capability-targets'),
  })
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<ListResponse<Job>>('/api/jobs'),
  })
  const update = useMutation({
    mutationFn: ({ target, status, evidenceText = '' }: {
      target: CapabilityTarget
      status: CapabilityTarget['status']
      evidenceText?: string
    }) => api<CapabilityTarget>(`/api/capability-targets/${target.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status, evidence_text: evidenceText }),
    }),
    onSuccess: (updated) => {
      client.invalidateQueries({ queryKey: ['capability-targets'] })
      if (updated.status === 'achieved') {
        setMessage('目标已达成：已加入事实库，可投递简历已更新。')
        setEvidenceTarget(null)
        setEvidence('')
      }
    },
  })

  const visibleTargets = useMemo(
    () => (targets.data?.items || []).filter((target) => !requestedJobId || target.job_id === requestedJobId),
    [requestedJobId, targets.data?.items],
  )
  const grouped = useMemo(() => {
    const result = new Map<string, CapabilityTarget[]>()
    for (const target of visibleTargets) {
      result.set(target.job_id, [...(result.get(target.job_id) || []), target])
    }
    return result
  }, [visibleTargets])
  const achieved = visibleTargets.filter((target) => target.status === 'achieved').length
  const jobNames = new Map((jobs.data?.items || []).map((job) => [job.id, `${job.company_name} · ${job.title}`]))

  const confirmAchievement = () => {
    if (!evidence.trim()) {
      setEvidenceError('请填写可核对的产出物证据。')
      return
    }
    if (!evidenceTarget) return
    setEvidenceError('')
    update.mutate({ target: evidenceTarget, status: 'achieved', evidenceText: evidence.trim() })
  }

  if (targets.isLoading || jobs.isLoading) return <Loading />
  if (targets.error || jobs.error) return <ErrorState error={targets.error || jobs.error} />

  return (
    <>
      <span className="badge">目标 → 练习 → 证据 → 事实</span>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-black">学习目标</h1>
          <p className="mt-2 text-sm text-black/55">完成真实产出并提交证据后，目标才会进入事实库。</p>
        </div>
        <div className="rounded-2xl bg-white px-5 py-3 text-right shadow-sm">
          <p className="text-xs text-black/50">整体进度</p>
          <b className="text-2xl">{achieved} / {visibleTargets.length}</b>
        </div>
      </div>
      {message && <p className="mt-5 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
      {update.error && <div className="mt-5"><ErrorState error={update.error} /></div>}
      <div className="mt-6 space-y-7">
        {grouped.size ? [...grouped.entries()].map(([jobId, items]) => (
          <section key={jobId}>
            <h2 className="text-xl font-bold">{jobNames.get(jobId) || '岗位信息待补充'}</h2>
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              {items.map((target) => (
                <article className="card" key={target.id}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${target.severity === 'high' ? 'bg-red-50 text-red-700' : target.severity === 'medium' ? 'bg-amber-50 text-amber-800' : 'bg-blue-50 text-blue-700'}`}>
                      {severityLabels[target.severity]}
                    </span>
                    <span className="text-sm text-black/55">{statusLabels[target.status]}</span>
                  </div>
                  <h3 className="mt-3 font-bold">{target.requirement}</h3>
                  <p className="mt-2 text-sm leading-6 text-black/70">产出物：{target.deliverable}</p>
                  <ul className="mt-3 space-y-1 text-sm text-black/60">
                    {target.acceptance_criteria_json.map((criterion) => <li key={criterion}>✓ {criterion}</li>)}
                  </ul>
                  <p className="mt-3 text-xs text-black/45">预计 {target.estimated_hours} 小时</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {target.status === 'pending' && (
                      <button className="btn-secondary" onClick={() => update.mutate({ target, status: 'in_progress' })}>
                        开始学习
                      </button>
                    )}
                    {target.status === 'in_progress' && (
                      <button className="btn" onClick={() => { setEvidenceTarget(target); setEvidence(''); setEvidenceError('') }}>
                        标记达成
                      </button>
                    )}
                    {target.status === 'achieved' && <p className="text-sm text-green-700">已加入事实库，可用于可投递简历。</p>}
                  </div>
                </article>
              ))}
            </div>
          </section>
        )) : <Empty title="还没有学习目标，请先在匹配报告中生成。" />}
      </div>
      {evidenceTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-5" role="dialog" aria-modal="true" aria-label="提交达成证据">
          <section className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
            <h2 className="text-xl font-bold">提交达成证据</h2>
            <p className="mt-2 text-sm text-black/60">{evidenceTarget.requirement}</p>
            <label className="mt-4 block">
              <span className="label">产出物证据（必填）</span>
              <textarea
                aria-label="产出物证据"
                className="field min-h-28"
                value={evidence}
                onChange={(event) => setEvidence(event.target.value)}
                placeholder="例如作品链接、文件名，或可核对的过程记录"
              />
            </label>
            {evidenceError && <p className="mt-2 text-sm text-red-700">{evidenceError}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-secondary" onClick={() => setEvidenceTarget(null)}>取消</button>
              <button className="btn" disabled={update.isPending} onClick={confirmAchievement}>确认达成</button>
            </div>
          </section>
        </div>
      )}
    </>
  )
}
