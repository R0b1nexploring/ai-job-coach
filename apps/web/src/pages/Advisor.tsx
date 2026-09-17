import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'


export function Advisor() {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ['advisor-queues'],
    queryFn: () => api<any>('/api/advisor/queues'),
    staleTime: 0,
  })
  const review = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) => api(`/api/advisor/resume-versions/${id}/review`, { method: 'POST', body: JSON.stringify({ approved, note: approved ? '顾问确认事实保护与表达均通过' : '退回用户修改' }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['advisor-queues'] }),
  })
  if (query.isLoading) return <Loading text="正在加载顾问队列…" />
  if (query.error) return <ErrorState error={query.error} />
  return <><span className="badge">仅分配客户</span><h1 className="page-title mt-3">顾问工作台</h1><p className="mt-2 text-ink-secondary">九个处理队列，敏感操作均由后端再次鉴权。</p>
    {review.error && <div className="mt-4"><ErrorState error={review.error} /></div>}
    <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data?.queues?.map((queue: any) => <section className="card" key={queue.name}><div className="flex justify-between"><h2 className="font-semibold">{queue.name}</h2><span className="badge">{queue.count}</span></div><div className="mt-4 space-y-3">{queue.items.length ? queue.items.map((item: any) => <div className="rounded-xl bg-cream p-3 text-sm" key={item.id}><b>{item.next_action}</b><p className="mt-1 text-ink-secondary">{item.user_name} · {item.package_name}</p><p className="mt-1 text-xs text-ink-muted">风险：{item.risk} · 截止：{item.due_at ? new Date(item.due_at).toLocaleString('zh-CN') : '未设置'}</p><Link className="mt-2 inline-block text-sage" to={`/advisor/clients/${item.user_id}`}>查看客户详情</Link>{item.type === 'resume' && item.can_review && <div className="mt-3 flex gap-2"><button className="btn-secondary" onClick={() => review.mutate({ id: item.id, approved: false })}>退回修改</button><button className="btn" onClick={() => review.mutate({ id: item.id, approved: true })}>批准简历</button></div>}{item.type === 'interview' && item.can_score && <InterviewScoreForm interviewId={item.id} />}</div>) : <p className="text-sm text-ink-muted">当前无任务</p>}</div></section>)}</div>
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
  return <form className="mt-3 space-y-3 border-t border-line pt-3" onSubmit={(event) => { event.preventDefault(); score.mutate() }}><div className="grid grid-cols-2 gap-2">{Object.entries(scoreLabels).map(([key, label]) => <label key={key}><span className="text-xs text-ink-secondary">{label}</span><input aria-label={label} className="field mt-1" type="number" min="1" max="5" value={scores[key]} onChange={(event) => setScores({ ...scores, [key]: Number(event.target.value) })} /></label>)}</div><label><span className="text-xs text-ink-secondary">复盘总结</span><textarea aria-label="复盘总结" className="field mt-1 min-h-20" value={summary} onChange={(event) => setSummary(event.target.value)} /></label><label><span className="text-xs text-ink-secondary">下一次训练任务</span><textarea aria-label="下一次训练任务" className="field mt-1 min-h-20" value={nextTask} onChange={(event) => setNextTask(event.target.value)} /></label><button className="btn w-full" disabled={score.isPending}>提交面试评分</button>{score.error && <ErrorState error={score.error} />}</form>
}


export function AdvisorClient() {
  const { id } = useParams()
  const query = useQuery({ queryKey: ['advisor-client', id], queryFn: () => api<any>(`/api/advisor/clients/${id}`) })
  if (query.isLoading) return <Loading text="正在加载客户时间线…" />
  if (query.error) return <ErrorState error={query.error} />
  const labels: Record<string, string> = { resumes: '简历', facts: '事实库', jobs: '岗位', matches: '匹配报告', resume_versions: '定制简历', applications: '投递', interviews: '面试', orders: '订单' }
  return <><Link to="/advisor" className="text-sage">← 返回工作台</Link><h1 className="page-title mt-4">{query.data.user.display_name}</h1><p className="mt-2 text-ink-secondary">{query.data.user.email}</p><section className="card mt-6"><h2 className="font-semibold">求职目标</h2><div className="mt-3 grid gap-2 text-sm md:grid-cols-3"><p>专业：{query.data.profile?.major || '待补充'}</p><p>目标城市：{query.data.profile?.target_cities_json?.join('、') || '待补充'}</p><p>目标岗位：{query.data.profile?.target_roles_json?.join('、') || '待补充'}</p></div></section><div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Object.entries(query.data.timeline).map(([name, items]) => <TimelineCard key={name} title={labels[name] || name} items={items as any[]} />)}</div></>
}

function TimelineCard({ title, items }: { title: string; items: any[] }) {
  const describe = (item: any) => item.display_name || item.label || [item.company_name, item.title].filter(Boolean).join(' · ') || item.recommendation || item.review_status || item.status || item.order_number || item.id?.slice(0, 8)
  return <section className="card"><div className="flex items-center justify-between"><h2 className="font-semibold">{title}</h2><span className="badge">{items.length}</span></div>{items.length ? <ul className="mt-3 space-y-2">{items.slice(0, 5).map((item) => <li className="rounded-lg bg-cream p-2 text-sm" key={item.id}>{describe(item)}{item.verification_status && <span className="ml-2 text-xs text-ink-muted">{item.verification_status}</span>}{typeof item.total_score === 'number' && <span className="ml-2 text-xs text-ink-muted">{item.total_score} 分</span>}</li>)}</ul> : <div className="mt-3"><Empty title="暂无记录" /></div>}</section>
}
