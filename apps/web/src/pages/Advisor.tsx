import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorState } from '../components/States'


export function Advisor() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['advisor-queues'], queryFn: () => api<any>('/api/advisor/queues') })
  const review = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) => api(`/api/advisor/resume-versions/${id}/review`, { method: 'POST', body: JSON.stringify({ approved, note: approved ? '顾问确认事实保护与表达均通过' : '退回用户修改' }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['advisor-queues'] }),
  })
  if (query.error) return <ErrorState error={query.error} />
  return <><span className="badge">仅分配客户</span><h1 className="mt-3 text-4xl font-black">顾问工作台</h1><p className="mt-2 text-black/60">九个处理队列，敏感操作均由后端再次鉴权。</p>
    {review.error && <div className="mt-4"><ErrorState error={review.error} /></div>}
    <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data?.queues?.map((queue: any) => <section className="card" key={queue.name}><div className="flex justify-between"><h2 className="font-bold">{queue.name}</h2><span className="badge">{queue.count}</span></div><div className="mt-4 space-y-3">{queue.items.length ? queue.items.map((item: any) => <div className="rounded-xl bg-cream p-3 text-sm" key={item.id}><b>{item.next_action}</b><p className="text-black/50">风险 {item.risk} · 用户 {item.user_id.slice(0, 6)}</p>{item.type === 'resume' && item.can_review && <div className="mt-3 flex gap-2"><button className="btn-secondary" onClick={() => review.mutate({ id: item.id, approved: false })}>退回修改</button><button className="btn" onClick={() => review.mutate({ id: item.id, approved: true })}>批准简历</button></div>}{item.type === 'interview' && item.can_score && <InterviewScoreForm interviewId={item.id} />}</div>) : <p className="text-sm text-black/40">当前无任务</p>}</div></section>)}</div>
  </>
}


const scoreLabels: Record<string, string> = {
  truthfulness: '内容真实性',
  structure: '回答结构',
  relevance: '岗位相关性',
  specificity: '具体程度',
  clarity: '表达清晰度',
  follow_up_stability: '追问稳定性',
}


function InterviewScoreForm({ interviewId }: { interviewId: string }) {
  const client = useQueryClient()
  const [scores, setScores] = useState<Record<string, number>>(Object.fromEntries(Object.keys(scoreLabels).map((key) => [key, 3])))
  const [summary, setSummary] = useState('回答基本真实，建议补充个人动作和选择依据。')
  const [nextTask, setNextTask] = useState('用 STAR 结构重写最薄弱的一题并再次练习。')
  const score = useMutation({
    mutationFn: () => api(`/api/advisor/interviews/${interviewId}/score`, { method: 'POST', body: JSON.stringify({ scorecard: scores, feedback: { summary, next_task: nextTask } }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['advisor-queues'] }),
  })
  return <form className="mt-3 space-y-3 border-t border-black/10 pt-3" onSubmit={(event) => { event.preventDefault(); score.mutate() }}><div className="grid grid-cols-2 gap-2">{Object.entries(scoreLabels).map(([key, label]) => <label key={key}><span className="text-xs text-black/60">{label}</span><input aria-label={label} className="field mt-1" type="number" min="1" max="5" value={scores[key]} onChange={(event) => setScores({ ...scores, [key]: Number(event.target.value) })} /></label>)}</div><label><span className="text-xs text-black/60">复盘总结</span><textarea aria-label="复盘总结" className="field mt-1 min-h-20" value={summary} onChange={(event) => setSummary(event.target.value)} /></label><label><span className="text-xs text-black/60">下一次训练任务</span><textarea aria-label="下一次训练任务" className="field mt-1 min-h-20" value={nextTask} onChange={(event) => setNextTask(event.target.value)} /></label><button className="btn w-full" disabled={score.isPending}>提交面试评分</button>{score.error && <ErrorState error={score.error} />}</form>
}


export function AdvisorClient() {
  const { id } = useParams()
  const query = useQuery({ queryKey: ['advisor-client', id], queryFn: () => api<any>(`/api/advisor/clients/${id}`) })
  if (query.isLoading) return <p>正在加载客户时间线…</p>
  if (query.error) return <ErrorState error={query.error} />
  return <><Link to="/advisor" className="text-sage">← 返回工作台</Link><h1 className="mt-4 text-4xl font-black">{query.data.user.display_name}</h1><p className="mt-2 text-black/50">{query.data.user.email}</p><div className="mt-6 grid gap-4 md:grid-cols-3">{Object.entries(query.data.timeline).map(([name, items]) => <section className="card" key={name}><h2 className="font-bold">{name}</h2><p className="mt-3 text-3xl font-black">{(items as any[]).length}</p></section>)}</div></>
}
