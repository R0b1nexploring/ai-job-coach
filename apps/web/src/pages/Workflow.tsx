import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'

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
  return <><span className="badge">合法状态机</span><h1 className="mt-3 text-4xl font-black">投递看板</h1>
    {update.error && <div className="mt-4"><ErrorState error={update.error} /></div>}
    <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data?.items?.length ? query.data.items.map((item: any) =>
      <article className="card" key={item.id}><p className="badge">{statusNames[item.status] || item.status}</p><p className="mt-3 break-all text-sm text-black/60">记录 {item.id.slice(0, 8)}</p>
        {next[item.status] && <button className="btn-secondary mt-5" onClick={() => update.mutate({ id: item.id, status: next[item.status] })}>推进到：{statusNames[next[item.status]]}</button>}
      </article>) : <Empty title="还没有投递记录。请先在匹配后加入队列。" />}</div></>
}

export function Interviews() {
  const query = useQuery({ queryKey: ['interviews'], queryFn: () => api<any>('/api/interviews') })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorState error={query.error} />
  return <><span className="badge">JD + 简历真实性追问</span><h1 className="mt-3 text-4xl font-black">模拟面试</h1><div className="mt-6 space-y-4">
    {query.data?.items?.length ? query.data.items.map((item: any) => <article className="card" key={item.id}><div className="flex justify-between"><h2 className="font-bold">题组 · {item.status}</h2><span className="badge">{item.question_set_json.questions?.length || 0} 题</span></div><ol className="mt-4 space-y-4">{item.question_set_json.questions?.map((question: any) => <li key={question.id}><p className="font-semibold">{question.question}</p><p className="text-sm text-black/50">考察：{question.why_asked} · 评分：{question.rubric.join(' / ')}</p></li>)}</ol>{Object.keys(item.scorecard_json || {}).length > 0 && <div className="mt-4 rounded-xl bg-green-50 p-3">顾问评分：{JSON.stringify(item.scorecard_json)}</div>}</article>) : <Empty title="暂无模拟面试。管理员发放演示额度后可创建。" />}
  </div></>
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
    <h2 className="mt-10 text-2xl font-bold">当前额度</h2><div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">{Object.entries(quotas.data || {}).map(([key, value]) => <div className="card" key={key}><p className="text-sm text-black/50">{key}</p><b className="text-3xl">{value}</b></div>)}</div>
    <h2 className="mt-10 text-2xl font-bold">额度变化</h2><div className="mt-4 space-y-3">{ledger.data?.items?.length ? ledger.data.items.map((item: any) => <article className="card flex justify-between" key={item.id}><div><b>{item.reason}</b><p className="text-sm text-black/50">{item.quota_type}</p></div><b className={item.delta > 0 ? 'text-green-700' : 'text-coral'}>{item.delta > 0 ? '+' : ''}{item.delta}</b></article>) : <Empty title="暂无额度变化。" />}</div>
  </>
}
