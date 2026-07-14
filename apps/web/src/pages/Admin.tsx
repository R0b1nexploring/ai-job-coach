import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'

export function AdminPackages() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-packages'], queryFn: () => api<any>('/api/admin/packages') })
  const toggle = useMutation({ mutationFn: ({ id, active }: { id: string; active: boolean }) => api(`/api/admin/packages/${id}`, { method: 'PATCH', body: JSON.stringify({ is_active: active }) }), onSuccess: () => client.invalidateQueries({ queryKey: ['admin-packages'] }) })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorState error={query.error} />
  return <><span className="badge">管理员</span><h1 className="mt-3 text-4xl font-black">套餐配置</h1><div className="mt-6 grid gap-4 md:grid-cols-2">{query.data?.items?.map((item: any) => <article className="card" key={item.id}><div className="flex justify-between"><div><h2 className="font-bold">{item.name}</h2><p className="text-sm text-black/50">{item.code} · ¥{item.price_cents / 100}</p></div><span className="badge">{item.is_active ? '启用' : '停用'}</span></div><p className="mt-3 text-sm">简历 {item.resume_quota} · 投递 {item.application_quota} · 面试 {item.interview_quota}</p><button className="btn-secondary mt-4" onClick={() => toggle.mutate({ id: item.id, active: !item.is_active })}>{item.is_active ? '停用' : '启用'}</button></article>)}</div></>
}

export function AdminQuotas() {
  const client = useQueryClient()
  const clients = useQuery({ queryKey: ['admin-clients'], queryFn: () => api<any>('/api/advisor/clients') })
  const ledger = useQuery({ queryKey: ['admin-ledger'], queryFn: () => api<any>('/api/admin/quotas/ledger') })
  const [userId, setUserId] = useState('')
  const [quotaType, setQuotaType] = useState('resume')
  const [amount, setAmount] = useState(1)
  const [reason, setReason] = useState('MVP-1 演示额度')
  const grant = useMutation({ mutationFn: () => api('/api/admin/quotas/grant', { method: 'POST', body: JSON.stringify({ user_id: userId, quota_type: quotaType, amount, reason, idempotency_key: `admin-${userId}-${quotaType}-${Date.now()}` }) }), onSuccess: () => client.invalidateQueries({ queryKey: ['admin-ledger'] }) })
  if (clients.isLoading || ledger.isLoading) return <Loading />
  if (clients.error || ledger.error) return <ErrorState error={clients.error || ledger.error} />
  return <><span className="badge">权限 · 审计 · 幂等</span><h1 className="mt-3 text-4xl font-black">演示额度管理</h1><form className="card mt-6 grid gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); grant.mutate() }}><label><span className="label">用户</span><select className="field" value={userId} onChange={(event) => setUserId(event.target.value)} required><option value="">请选择</option>{clients.data?.items?.map((item: any) => <option key={item.id} value={item.id}>{item.display_name} · {item.email}</option>)}</select></label><label><span className="label">额度类型</span><select className="field" value={quotaType} onChange={(event) => setQuotaType(event.target.value)}><option value="match">match</option><option value="resume">resume</option><option value="application">application</option><option value="interview">interview</option></select></label><label><span className="label">数量（负数为调整扣减）</span><input className="field" type="number" value={amount} onChange={(event) => setAmount(Number(event.target.value))} /></label><label><span className="label">原因</span><input className="field" value={reason} onChange={(event) => setReason(event.target.value)} /></label><button className="btn md:col-span-2" disabled={!userId || !amount}>发放并记录审计</button>{grant.error && <div className="md:col-span-2"><ErrorState error={grant.error} /></div>}{grant.isSuccess && <p className="text-green-700 md:col-span-2">额度已写入账本。</p>}</form><h2 className="mt-10 text-2xl font-bold">全部额度账本</h2><div className="mt-4 space-y-3">{ledger.data?.items?.length ? ledger.data.items.map((item: any) => <article className="card flex justify-between" key={item.id}><div><b>{item.reason}</b><p className="text-sm text-black/50">用户 {item.user_id.slice(0, 8)} · {item.quota_type}</p></div><b>{item.delta > 0 ? '+' : ''}{item.delta}</b></article>) : <Empty title="暂无额度记录。" />}</div></>
}
