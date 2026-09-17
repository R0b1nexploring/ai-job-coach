import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorState, Loading } from '../components/States'
import { Alert, PageHeader } from '../components/ui'

export function Settings() {
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => api<any>('/api/profile') })
  const remove = useMutation({ mutationFn: () => api('/api/account', { method: 'DELETE' }) })
  if (profile.isLoading) return <Loading />
  if (profile.error) return <ErrorState error={profile.error} />
  return (
    <>
      <PageHeader kicker="账户" title="设置" lead="管理求职偏好、个人数据与服务状态。" />
      <div className="mt-6 grid gap-5 lg:grid-cols-[180px_minmax(0,1fr)]">
        <nav className="space-y-1" aria-label="设置分类">
          <a href="#preferences" className="block rounded-lg bg-sage/[0.09] px-3 py-2.5 text-sm font-semibold text-sage">求职偏好</a>
          <a href="#privacy" className="block rounded-lg px-3 py-2.5 text-sm font-medium text-ink-secondary hover:bg-ink/[0.03]">数据与隐私</a>
          <a href="#service" className="block rounded-lg px-3 py-2.5 text-sm font-medium text-ink-secondary hover:bg-ink/[0.03]">服务状态</a>
        </nav>
        <div className="space-y-4">
      <section className="card" id="preferences">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold tracking-tight">求职偏好</h2>
            <p className="mt-2 leading-7 text-ink-secondary">
              目标城市：{profile.data?.target_cities?.join('、') || '待补充'}
              <br />
              目标岗位：{profile.data?.target_roles?.join('、') || '待补充'}
            </p>
          </div>
          <Link className="btn-secondary" to="/app/onboarding">修改求职偏好</Link>
        </div>
      </section>
      <section className="card" id="privacy">
        <h2 className="font-semibold tracking-tight">个人资料权利</h2>
        <p className="mt-2 text-sm leading-6 text-ink-secondary">资料仅用于本次求职服务，默认保存 180 天，案例展示授权默认关闭。你可以导出数据或请求删除账号。</p>
        <div className="mt-4 flex flex-wrap gap-3">
          <a className="btn-secondary" href="/api/account/export">下载个人数据</a>
          <button
            className="btn-danger"
            onClick={() => confirm('确定请求删除账号？管理员执行清理后不可恢复。') && remove.mutate()}
          >
            请求删除账号
          </button>
        </div>
        {remove.error && <div className="mt-3"><ErrorState error={remove.error} /></div>}
        {remove.isSuccess && <div className="mt-3"><Alert tone="success">删除请求已提交。</Alert></div>}
      </section>
      <section className="card" id="service">
        <h2 className="font-semibold tracking-tight">服务状态</h2>
        <p className="mt-2 text-sm leading-6 text-ink-secondary">忘记密码邮件尚未接入；MVP 使用站内通知与控制台 Mock。</p>
      </section>
        </div>
      </div>
    </>
  )
}
