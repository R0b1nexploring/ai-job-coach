import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'

export function AdminPackages() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-packages'], queryFn: () => api<any>('/api/admin/packages') })
  const [draft, setDraft] = useState({ code: '', name: '', price_cents: 0, billing_period: 'once', resume_quota: 0, application_quota: 0, interview_quota: 0, features: '' })
  const create = useMutation({
    mutationFn: () => api('/api/admin/packages', { method: 'POST', body: JSON.stringify({ ...draft, features_json: draft.features.split('，').map((value) => value.trim()).filter(Boolean), features: undefined }) }),
    onSuccess: () => { setDraft({ code: '', name: '', price_cents: 0, billing_period: 'once', resume_quota: 0, application_quota: 0, interview_quota: 0, features: '' }); client.invalidateQueries({ queryKey: ['admin-packages'] }) },
  })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorState error={query.error} />
  const numberField = (key: 'price_cents' | 'resume_quota' | 'application_quota' | 'interview_quota', label: string) => <label><span className="label">{label}</span><input className="field" type="number" min="0" value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: Number(event.target.value) })} /></label>
  return <><span className="badge">管理员 · 完整 CRUD</span><h1 className="mt-3 text-4xl font-black">套餐配置</h1><form className="card mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><label><span className="label">套餐代码</span><input aria-label="套餐代码" className="field" pattern="[a-z0-9_-]{2,50}" value={draft.code} onChange={(event) => setDraft({ ...draft, code: event.target.value })} required /></label><label><span className="label">套餐名称</span><input aria-label="套餐名称" className="field" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label><label><span className="label">计费周期</span><select aria-label="计费周期" className="field" value={draft.billing_period} onChange={(event) => setDraft({ ...draft, billing_period: event.target.value })}><option value="once">一次性</option><option value="month">每月</option><option value="year">每年</option></select></label>{numberField('price_cents', '价格（分）')}{numberField('resume_quota', '简历额度')}{numberField('application_quota', '投递额度')}{numberField('interview_quota', '面试额度')}<label><span className="label">功能（中文逗号分隔）</span><input aria-label="套餐功能" className="field" value={draft.features} onChange={(event) => setDraft({ ...draft, features: event.target.value })} /></label><button className="btn md:col-span-2 xl:col-span-4" disabled={create.isPending}>创建套餐</button>{create.error && <div className="md:col-span-2 xl:col-span-4"><ErrorState error={create.error} /></div>}</form><div className="mt-6 grid gap-4 xl:grid-cols-2">{query.data?.items?.length ? query.data.items.map((item: any) => <PackageEditor item={item} key={item.id} />) : <Empty title="还没有套餐。" />}</div></>
}

function PackageEditor({ item }: { item: any }) {
  const client = useQueryClient()
  const [form, setForm] = useState({ name: item.name, price_cents: item.price_cents, billing_period: item.billing_period, resume_quota: item.resume_quota, application_quota: item.application_quota, interview_quota: item.interview_quota, features: item.features_json.join('，') })
  const refresh = () => client.invalidateQueries({ queryKey: ['admin-packages'] })
  const save = useMutation({ mutationFn: () => api(`/api/admin/packages/${item.id}`, { method: 'PATCH', body: JSON.stringify({ ...form, features_json: form.features.split('，').map((value: string) => value.trim()).filter(Boolean), features: undefined }) }), onSuccess: refresh })
  const toggle = useMutation({ mutationFn: () => item.is_active ? api(`/api/admin/packages/${item.id}`, { method: 'DELETE' }) : api(`/api/admin/packages/${item.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: true }) }), onSuccess: refresh })
  return <article className="card"><div className="flex items-center justify-between"><div><h2 className="font-bold">{item.code}</h2><p className="text-xs text-black/45">创建后代码不可修改</p></div><span className="badge">{item.is_active ? '启用' : '停用'}</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2"><label><span className="label">名称</span><input className="field" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label><span className="label">价格（分）</span><input className="field" type="number" min="0" value={form.price_cents} onChange={(event) => setForm({ ...form, price_cents: Number(event.target.value) })} /></label><label><span className="label">计费周期</span><select className="field" value={form.billing_period} onChange={(event) => setForm({ ...form, billing_period: event.target.value })}><option value="once">一次性</option><option value="month">每月</option><option value="year">每年</option></select></label><label><span className="label">简历额度</span><input className="field" type="number" min="0" value={form.resume_quota} onChange={(event) => setForm({ ...form, resume_quota: Number(event.target.value) })} /></label><label><span className="label">投递额度</span><input className="field" type="number" min="0" value={form.application_quota} onChange={(event) => setForm({ ...form, application_quota: Number(event.target.value) })} /></label><label><span className="label">面试额度</span><input className="field" type="number" min="0" value={form.interview_quota} onChange={(event) => setForm({ ...form, interview_quota: Number(event.target.value) })} /></label><label className="sm:col-span-2"><span className="label">功能</span><input className="field" value={form.features} onChange={(event) => setForm({ ...form, features: event.target.value })} /></label></div><div className="mt-4 flex gap-2"><button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>保存套餐</button><button className="btn-secondary" disabled={toggle.isPending} onClick={() => toggle.mutate()}>{item.is_active ? '停用套餐' : '重新启用'}</button></div>{(save.error || toggle.error) && <div className="mt-3"><ErrorState error={save.error || toggle.error} /></div>}</article>
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

export function AdminAccounts() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-deletion-requests'], queryFn: () => api<any>('/api/admin/accounts/deletion-requests') })
  const purge = useMutation({
    mutationFn: (userId: string) => api(`/api/admin/accounts/${userId}/purge`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['admin-deletion-requests'] }),
  })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorState error={query.error} />
  return <><span className="badge">隐私 · 不可逆操作</span><h1 className="mt-3 text-4xl font-black">账号清理</h1><p className="mt-3 max-w-3xl text-black/60">这里只显示用户主动提交的删除申请。执行后会删除上传和导出文件、清空个人内容并匿名化账号，审计骨架会保留。</p>{purge.error && <div className="mt-4"><ErrorState error={purge.error} /></div>}<div className="mt-6 space-y-4">{query.data?.items?.length ? query.data.items.map((item: any) => <article className="card flex flex-wrap items-center justify-between gap-4" key={item.id}><div><h2 className="font-bold">{item.display_name}</h2><p className="mt-1 text-sm text-black/50">{item.email} · 申请状态：待清理</p><p className="mt-1 text-xs text-black/40">最后更新：{new Date(item.updated_at).toLocaleString('zh-CN')}</p></div><button className="rounded-xl border border-red-300 px-4 py-2 text-red-700" disabled={purge.isPending} onClick={() => confirm(`确定永久清理 ${item.display_name} 的个人内容？`) && purge.mutate(item.id)}>执行清理</button></article>) : <Empty title="当前没有待处理的账号删除申请。" />}</div>{purge.isSuccess && <p className="mt-4 rounded-xl bg-green-50 p-3 text-green-700">账号内容已完成清理并写入审计日志。</p>}</>
}

export function AdminSystem() {
  const query = useQuery({ queryKey: ['admin-system-status'], queryFn: () => api<any>('/api/admin/system/status') })
  if (query.isLoading) return <Loading text="正在检查系统状态…" />
  if (query.error) return <ErrorState error={query.error} />
  const providers = query.data.providers
  const maintenance = query.data.maintenance
  return <><span className="badge">不显示密钥 · 只显示配置状态</span><h1 className="mt-3 text-4xl font-black">系统状态</h1><div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4"><StatusCard title="AI Provider" ok={providers.llm.operational} detail={`${providers.llm.provider} · ${providers.llm.notice}`} /><StatusCard title="岗位来源" ok={providers.jobs.operational} detail={providers.jobs.providers.join(' / ')} /><StatusCard title="文件存储" ok={providers.storage.operational} detail={`${providers.storage.provider} · ${providers.storage.notice}`} /><StatusCard title="支付边界" ok={providers.payment.operational} detail={providers.payment.notice} /></div>{providers.llm.missing_configuration.length > 0 && <section className="card mt-4 border border-amber-200 bg-amber-50"><h2 className="font-bold text-amber-900">真实 AI 配置不完整</h2><p className="mt-2 text-sm text-amber-900">缺少：{providers.llm.missing_configuration.join('、')}。系统当前会安全回退 Mock。</p></section>}<section className="card mt-6"><h2 className="font-bold">维护任务预览</h2><p className="mt-2 text-sm text-black/60">此页面不会执行删除。命令行省略 `--execute` 时同样只预览。</p><div className="mt-4 grid gap-3 sm:grid-cols-3"><p>保留期到期账号：<b>{maintenance.expired_user_count}</b></p><p>超过宽限期的删除申请：<b>{maintenance.deletion_request_count}</b></p><p>待标记过期岗位：<b>{maintenance.stale_job_count}</b></p></div></section></>
}

function StatusCard({ title, ok, detail }: { title: string; ok: boolean; detail: string }) {
  return <article className="card"><span className={`badge ${ok ? '' : 'bg-amber-100 text-amber-900'}`}>{ok ? '可用' : '需配置'}</span><h2 className="mt-3 font-bold">{title}</h2><p className="mt-2 text-sm text-black/60">{detail}</p></article>
}
