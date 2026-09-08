import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { PublicHeader } from '../components/Layout'

export function Home() {
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ status: string }>('/api/health'), retry: 1 })
  return (
    <>
      <PublicHeader />
      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 py-14 pb-24 md:grid-cols-[1.15fr_.85fr] md:py-20 md:pb-28">
          <div>
            <span className="badge">机械 · 制造 · 生物医药工程</span>
            <h1 className="mt-5 text-5xl font-bold leading-[1.08] tracking-tight md:text-6xl lg:text-7xl">
              把求职变成<br />
              <span className="text-sage">有证据的行动</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-8 text-black/65">
              粘贴岗位要求，生成一份可投递的求职简历和一份提升蓝图，再带上对应的面试指南去准备。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link className="btn px-5 py-3" to="/register">免费开始</Link>
              <Link className="btn-secondary px-5 py-3" to="/pricing">查看服务</Link>
            </div>
            <p className="mt-5 text-sm" data-testid="health">
              {health.isLoading ? '正在检查服务…' : health.isError ? '服务暂不可用' : '● 服务正常'}
            </p>
          </div>
          <div className="relative mx-auto w-full max-w-md pb-8">
            <div className="card -rotate-1 border-sage/15 bg-sage pb-20 text-white">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/60">求职版</p>
              <h2 className="mt-4 text-2xl font-bold">针对这一份 JD</h2>
              <div className="mt-6 space-y-3 text-sm leading-6 text-white/80">
                <p>✓ 按岗位要求重组经历</p>
                <p>✓ HTML / DOCX / PDF 同源导出</p>
              </div>
            </div>
            <div className="card absolute bottom-0 right-0 w-[88%] rotate-2 border-coral/20">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-coral">蓝图 Plus</p>
              <p className="mt-3 text-sm leading-6 text-black/65">未达成的目标用 * 标出，面试时不会假装已经做过。</p>
            </div>
          </div>
        </section>
        <section className="border-y border-black/5 bg-white/60 py-16">
          <div className="mx-auto grid max-w-6xl gap-5 px-5 md:grid-cols-3">
            {[
              ['01', '粘贴岗位要求', '复制招聘页面里的职位描述，先让系统理解这个岗位。'],
              ['02', '生成双轨简历', '一次得到求职版和蓝图 Plus，上传简历可让结果更像你。'],
              ['03', '导出并准备面试', '下载 HTML / DOCX / PDF，再打开绑定这份简历的面试指南。'],
            ].map((item) => (
              <div className="card" key={item[0]}>
                <b className="text-coral">{item[0]}</b>
                <h3 className="mt-8 text-xl font-bold">{item[1]}</h3>
                <p className="mt-3 text-sm leading-6 text-black/55">{item[2]}</p>
              </div>
            ))}
          </div>
        </section>
        <section className="mx-auto max-w-6xl px-5 py-14 text-sm text-black/60">
          <p>我们不编造经历、不保存招聘平台密码、不绕过验证码、不承诺 Offer。案例展示授权默认关闭。</p>
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
      <main className="mx-auto max-w-6xl px-5 py-12">
        <span className="badge">透明额度 · 随时可查</span>
        <h1 className="page-title mt-4">套餐说明</h1>
        <p className="page-lead">额度用在生成与准备上，不包含无限修改或结果保证。</p>
        <div className="mt-8 grid gap-4 md:grid-cols-4">
          {q.data?.items?.map((p: any) => (
            <div className="card flex flex-col" key={p.id}>
              <h2 className="text-xl font-bold">{p.name}</h2>
              <p className="my-4 text-3xl font-bold tracking-tight">¥{p.price_cents / 100}</p>
              <p className="min-h-16 flex-1 text-sm leading-6 text-black/60">{p.features_json.join(' · ')}</p>
              <Link className="btn mt-5 w-full" to="/app/orders">查看演示额度</Link>
            </div>
          )) || <p>正在加载套餐…</p>}
        </div>
        <p className="alert alert-warning mt-8">MVP-1 在线支付尚未开放；额度由种子脚本或管理员发放。不包含无限修改、无人值守代投或结果保证。</p>
      </main>
    </>
  )
}
