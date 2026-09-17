import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { PublicHeader } from '../components/Layout'
import { Icon, StatusChip } from '../components/ui'

export function Home() {
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ status: string }>('/api/health'), retry: 1 })
  return (
    <>
      <PublicHeader />
      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 py-16 md:grid-cols-[1fr_1fr] md:py-24">
          <div>
            <span className="badge"><span className="h-1.5 w-1.5 rounded-full bg-sage" />面向理工科求职者</span>
            <h1 className="mt-6 font-display text-[36px] font-medium leading-[1.08] tracking-[-0.01em] sm:text-[44px] lg:text-[56px]">
              把求职变成<br /><span className="text-sage">清晰的下一步</span>
            </h1>
            <p className="mt-6 max-w-xl text-base leading-8 text-ink-secondary sm:text-lg">
              粘贴岗位要求，生成一份可投递的求职简历和一份提升蓝图，再带上对应的面试指南去准备。
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link className="btn px-5" to="/register">免费开始<Icon name="chevron-right" /></Link>
              <Link className="btn-secondary px-5" to="/pricing">查看服务</Link>
            </div>
            <div className="mt-5" data-testid="health">
              <StatusChip tone={health.isError ? 'danger' : health.isLoading ? 'neutral' : 'success'}>
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {health.isLoading ? '正在检查服务…' : health.isError ? '服务暂不可用' : '服务正常'}
              </StatusChip>
            </div>
          </div>
          <div className="overflow-hidden rounded-2xl border border-line bg-white shadow-lift">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="flex items-center gap-2 text-xs font-medium text-ink-muted"><Icon name="studio" />简历工作台</div>
              <StatusChip tone="success">已完成</StatusChip>
            </div>
            <div className="grid min-h-[390px] grid-cols-[82px_minmax(0,1fr)] sm:grid-cols-[110px_1fr]">
              <div className="border-r border-line bg-ink/[0.015] p-2 sm:p-3">
                {['岗位', '素材', '双版简历', '导出指南'].map((item, index) => (
                  <div className={`mb-1 rounded-lg px-2 py-2 text-xs ${index === 2 ? 'bg-sage/[0.09] font-semibold text-sage' : 'text-ink-muted'}`} key={item}>0{index + 1} {item}</div>
                ))}
              </div>
              <div className="min-w-0 p-3 sm:p-4">
                <div className="flex items-center justify-between">
                  <div><p className="eyebrow">两份结果</p><h2 className="mt-1 text-lg font-semibold">求职版 · 蓝图 Plus</h2></div>
                  <div className="segmented hidden sm:inline-flex"><span className="segmented-item segmented-item-active py-1.5">求职版</span><span className="segmented-item py-1.5">蓝图</span></div>
                </div>
                <div className="mx-auto mt-5 aspect-[210/297] w-[66%] border border-line bg-white p-5 shadow-lift">
                  <div className="h-3 w-2/5 rounded bg-slate-700" />
                  <div className="mt-3 h-1.5 w-3/5 rounded bg-ink/10" />
                  <div className="mt-6 h-2 w-1/3 rounded bg-slate-600" />
                  <div className="mt-2 h-px bg-slate-300" />
                  {[1, 2, 3, 4, 5, 6].map((line) => <div key={line} className={`mt-2 h-1.5 rounded bg-ink/[0.09] ${line % 2 ? 'w-full' : 'w-4/5'}`} />)}
                </div>
              </div>
            </div>
          </div>
        </section>
        <section className="border-y border-line bg-white py-14">
          <div className="mx-auto grid max-w-6xl gap-px overflow-hidden rounded-2xl border border-line bg-ink/[0.07] md:grid-cols-3">
            {[
              ['01', '粘贴岗位要求', '复制招聘页面里的职位描述，先让系统理解这个岗位。'],
              ['02', '生成双轨简历', '一次得到求职版和蓝图 Plus，上传简历可让结果更像你。'],
              ['03', '导出并准备面试', '下载 HTML / DOCX / PDF，再打开绑定这份简历的面试指南。'],
            ].map((item) => (
              <div className="bg-white p-6" key={item[0]}>
                <b className="text-xs text-sage">{item[0]}</b>
                <h3 className="mt-8 text-lg font-semibold">{item[1]}</h3>
                <p className="mt-2 text-sm leading-6 text-ink-secondary">{item[2]}</p>
              </div>
            ))}
          </div>
        </section>
        <section className="mx-auto flex max-w-6xl flex-col justify-between gap-4 px-5 py-12 text-sm text-ink-muted sm:flex-row">
          <p>不编造经历，不保存招聘平台密码，不承诺 Offer。</p>
          <p>案例展示授权默认关闭。</p>
        </section>
      </main>
    </>
  )
}

export function Pricing() {
  const q = useQuery({ queryKey: ['packages'], queryFn: () => api<any>('/api/packages') })
  return (
    <>
      <PublicHeader />
      <main className="mx-auto max-w-6xl px-5 py-14">
        <span className="badge">透明额度 · 随时可查</span>
        <h1 className="mt-5 font-display text-[34px] font-medium leading-[1.15] tracking-[-0.01em]">套餐说明</h1>
        <p className="page-lead">额度用在生成与准备上，不包含无限修改或结果保证。</p>
        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {q.data?.items?.map((p: any) => (
            <div className="card flex min-h-64 flex-col" key={p.id}>
              <p className="eyebrow">套餐</p>
              <h2 className="mt-2 text-lg font-semibold">{p.name}</h2>
              <p className="my-5 font-display text-[34px] font-medium leading-none tabular-nums">¥{p.price_cents / 100}</p>
              <p className="min-h-16 flex-1 text-sm leading-6 text-ink-secondary">{p.features_json.join(' · ')}</p>
              <Link className="btn-secondary mt-5 w-full" to="/app/orders">查看演示额度</Link>
            </div>
          )) || <p>正在加载套餐…</p>}
        </div>
        <p className="alert alert-warning mt-8">MVP-1 在线支付尚未开放；额度由种子脚本或管理员发放。不包含无限修改、无人值守代投或结果保证。</p>
      </main>
    </>
  )
}
