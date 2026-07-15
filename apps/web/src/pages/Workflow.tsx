import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'
import { quotaLabels } from '../app/labels'

const statusNames: Record<string, string> = {
  pending_confirmation: '待确认', preparing_resume: '待生成简历', ready_to_apply: '待投递',
  applied: '已投递', contacted: '有沟通', assessment: '测评', interview: '面试',
  offer: 'Offer', rejected: '拒绝', withdrawn: '已撤回',
}
const next: Record<string, string> = {
  pending_confirmation: 'preparing_resume', preparing_resume: 'ready_to_apply',
  ready_to_apply: 'applied', applied: 'contacted', contacted: 'interview', interview: 'offer',
}

export function Applications() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['applications'], queryFn: () => api<any>('/api/applications') })
  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api(`/api/applications/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status, note: '用户在看板更新' }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['applications'] }),
  })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorState error={query.error} />
  return <><span className="badge">合法状态机</span><h1 className="mt-3 text-4xl font-black">投递看板</h1>
    {update.error && <div className="mt-4"><ErrorState error={update.error} /></div>}
    <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data?.items?.length ? query.data.items.map((item: any) =>
      <article className="card" key={item.id}><p className="badge">{statusNames[item.status] || item.status}</p><p className="mt-3 break-all text-sm text-black/60">记录 {item.id.slice(0, 8)}</p>
        {next[item.status] && <button className="btn-secondary mt-5" onClick={() => update.mutate({ id: item.id, status: next[item.status] })}>推进到：{statusNames[next[item.status]]}</button>}
      </article>) : <Empty title="还没有投递记录。请先在匹配后加入队列。" />}</div></>
}

export function Interviews() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['interviews'], queryFn: () => api<any>('/api/interviews') })
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api<any>('/api/jobs') })
  const versions = useQuery({ queryKey: ['resume-versions'], queryFn: () => api<any>('/api/resume-versions') })
  const [jobId, setJobId] = useState('')
  const [versionId, setVersionId] = useState('')
  const create = useMutation({
    mutationFn: () => api<any>('/api/interviews', {
      method: 'POST',
      headers: { 'Idempotency-Key': `web-interview-${jobId}-${Date.now()}` },
      body: JSON.stringify({ job_id: jobId, resume_version_id: versionId || null }),
    }),
    onSuccess: () => {
      setJobId('')
      setVersionId('')
      client.invalidateQueries({ queryKey: ['interviews'] })
      client.invalidateQueries({ queryKey: ['quotas'] })
    },
  })
  if (query.isLoading || jobs.isLoading || versions.isLoading) return <Loading />
  if (query.error || jobs.error || versions.error) return <ErrorState error={query.error || jobs.error || versions.error} />
  const approvedVersions = versions.data?.items?.filter((item: any) => item.job_id === jobId && item.guard_status === 'passed' && item.review_status === 'approved') || []
  return <><span className="badge">JD + 简历真实性追问</span><h1 className="mt-3 text-4xl font-black">模拟面试</h1>
    <form className="card mt-6 grid gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); create.mutate() }}>
      <label><span className="label">目标岗位</span><select aria-label="目标岗位" className="field" value={jobId} onChange={(event) => { setJobId(event.target.value); setVersionId('') }} required><option value="">请选择岗位</option>{jobs.data?.items?.map((job: any) => <option key={job.id} value={job.id}>{job.company_name} · {job.title}</option>)}</select></label>
      <label><span className="label">已批准定制简历（可选）</span><select aria-label="已批准定制简历" className="field" value={versionId} onChange={(event) => setVersionId(event.target.value)}><option value="">不关联定制版本</option>{approvedVersions.map((version: any) => <option key={version.id} value={version.id}>{version.title}</option>)}</select></label>
      <button className="btn md:col-span-2" disabled={!jobId || create.isPending}>{create.isPending ? '正在生成题目…' : '生成模拟面试题'}</button>
      {create.error && <div className="md:col-span-2"><ErrorState error={create.error} /></div>}
      {create.isSuccess && <p className="text-green-700 md:col-span-2">题目已生成，请填写回答后提交顾问评分。</p>}
    </form>
    <div className="mt-6 space-y-4">{query.data?.items?.length ? query.data.items.map((item: any) => <InterviewCard item={item} key={item.id} />) : <Empty title="暂无模拟面试。管理员发放演示额度后可创建。" />}</div>
  </>
}

const interviewStatus: Record<string, string> = { draft: '待作答', submitted: '待顾问评分', scored: '已完成复盘' }

function InterviewCard({ item }: { item: any }) {
  const client = useQueryClient()
  const questions = item.question_set_json.questions || []
  const [answers, setAnswers] = useState<Record<string, string>>(item.answers_json || {})
  const save = useMutation({
    mutationFn: () => api<any>(`/api/interviews/${item.id}/answers`, { method: 'PATCH', body: JSON.stringify({ answers }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['interviews'] }),
  })
  const submit = useMutation({
    mutationFn: async () => {
      await api(`/api/interviews/${item.id}/answers`, { method: 'PATCH', body: JSON.stringify({ answers }) })
      return api(`/api/interviews/${item.id}/submit`, { method: 'POST' })
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['interviews'] }),
  })
  const error = save.error || submit.error
  return <article className="card"><div className="flex flex-wrap justify-between gap-3"><h2 className="font-bold">模拟题组</h2><div className="flex gap-2"><span className="badge">{interviewStatus[item.status] || item.status}</span><span className="badge">{questions.length} 题</span></div></div>
    <ol className="mt-4 space-y-5">{questions.map((question: any, index: number) => <li key={question.id}><p className="font-semibold">{index + 1}. {question.question}</p><p className="mt-1 text-sm text-black/50">考察：{question.why_asked} · 评分：{question.rubric.join(' / ')}</p>{item.status === 'draft' && <textarea aria-label={`回答第 ${index + 1} 题`} className="field mt-3 min-h-24" value={answers[question.id] || ''} onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })} placeholder="按真实经历填写；不知道可以明确说明。" />}</li>)}</ol>
    {item.status === 'draft' && <div className="mt-5 flex flex-wrap gap-3"><button className="btn-secondary" disabled={save.isPending} onClick={() => save.mutate()}>保存回答</button><button className="btn" disabled={submit.isPending || !Object.values(answers).some((answer) => answer.trim())} onClick={() => submit.mutate()}>提交顾问评分</button></div>}
    {item.status === 'submitted' && <p className="mt-5 rounded-xl bg-amber-50 p-3 text-amber-800">回答已锁定，等待顾问评分与复盘。</p>}
    {item.status === 'scored' && <div className="mt-5 rounded-xl bg-green-50 p-4"><h3 className="font-bold">顾问评分</h3><div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3">{Object.entries(item.scorecard_json || {}).map(([name, score]) => <p key={name} className="rounded-lg bg-white p-2 text-sm">{name}：<b>{String(score)}</b></p>)}</div><p className="mt-3 text-sm">{item.feedback_json?.summary || '顾问已完成评分。'}</p>{item.feedback_json?.next_task && <p className="mt-2 text-sm text-green-800">下一步：{item.feedback_json.next_task}</p>}</div>}
    {error && <div className="mt-4"><ErrorState error={error} /></div>}
  </article>
}

export function Orders() {
  const packages = useQuery({ queryKey: ['packages'], queryFn: () => api<any>('/api/packages') })
  const quotas = useQuery({ queryKey: ['quotas'], queryFn: () => api<Record<string, number>>('/api/quotas') })
  const ledger = useQuery({ queryKey: ['quota-ledger'], queryFn: () => api<any>('/api/quotas/ledger') })
  if (packages.isLoading || quotas.isLoading || ledger.isLoading) return <Loading />
  if (packages.error || quotas.error || ledger.error) return <ErrorState error={packages.error || quotas.error || ledger.error} />
  return <><span className="badge">MVP-1 演示额度</span><h1 className="mt-3 text-4xl font-black">套餐与额度</h1>
    <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800">在线支付尚未开放。当前额度由种子脚本或管理员发放，不代表真实付款。</p>
    <div className="mt-6 grid gap-4 md:grid-cols-4">{packages.data?.items?.map((item: any) => <article className="card" key={item.id}><h2 className="font-bold">{item.name}</h2><p className="my-3 text-3xl font-black">¥{item.price_cents / 100}</p><p className="text-xs text-black/50">简历 {item.resume_quota} · 投递 {item.application_quota} · 面试 {item.interview_quota}</p><p className="mt-4 text-sm">{item.features_json.join(' · ')}</p></article>)}</div>
    <h2 className="mt-10 text-2xl font-bold">当前额度</h2><div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">{Object.entries(quotas.data || {}).map(([key, value]) => <div className="card" key={key}><p className="text-sm text-black/50">{quotaLabels[key] || '其他额度'}</p><b className="text-3xl">{value}</b></div>)}</div>
    <h2 className="mt-10 text-2xl font-bold">额度变化</h2><div className="mt-4 space-y-3">{ledger.data?.items?.length ? ledger.data.items.map((item: any) => <article className="card flex justify-between" key={item.id}><div><b>{item.reason}</b><p className="text-sm text-black/50">{quotaLabels[item.quota_type] || '其他额度'}</p></div><b className={item.delta > 0 ? 'text-green-700' : 'text-coral'}>{item.delta > 0 ? '+' : ''}{item.delta}</b></article>) : <Empty title="暂无额度变化。" />}</div>
  </>
}
