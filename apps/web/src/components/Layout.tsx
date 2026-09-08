import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../app/AuthContext'
import { useQuery } from '@tanstack/react-query'
import { clearOnboardingDraft } from '../utils/onboardingDraft'
import { Icon, Logo } from './ui'

const links: Array<[string, string, 'studio' | 'guides' | 'settings']> = [
  ['/app/resume-studio', '工作台', 'studio'],
  ['/app/guides', '面试指南', 'guides'],
  ['/app/settings', '设置', 'settings'],
]

export function PublicHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-black/5 bg-cream/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
        <Link to="/" className="text-ink"><Logo /></Link>
        <nav className="flex items-center gap-2 sm:gap-3">
          <Link to="/pricing" className="px-2 text-sm font-medium text-black/60 hover:text-ink">套餐</Link>
          <Link to="/login" className="btn-secondary px-3 py-2 text-sm">登录</Link>
          <Link to="/register" className="btn px-3 py-2 text-sm">免费开始</Link>
        </nav>
      </div>
    </header>
  )
}

export function AppLayout() {
  const { user, refresh } = useAuth()
  const navigate = useNavigate()
  const notifications = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api<{ unread_count: number }>('/api/notifications'),
    enabled: !!user,
  })
  const logout = async () => {
    try {
      await api('/api/auth/logout', { method: 'POST' })
      refresh()
      navigate('/')
    } finally {
      clearOnboardingDraft(user?.id)
    }
  }
  const initials = (user?.display_name || user?.email || '用').slice(0, 1)
  return (
    <div className="min-h-screen md:flex">
      <aside className="sticky top-0 z-20 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-white/10 bg-ink px-3 py-3 text-white md:min-h-screen md:w-64 md:flex-col md:flex-nowrap md:items-stretch md:gap-0 md:border-b-0 md:border-r md:border-white/5 md:px-0 md:py-0">
        <Link to="/" className="text-white md:px-5 md:pt-6">
          <Logo />
        </Link>
        <p className="hidden text-xs text-white/45 md:mt-3 md:block md:px-5">
          {user?.display_name} · 未读 {notifications.data?.unread_count ?? 0}
        </p>
        <nav className="order-3 flex w-full gap-1 overflow-x-auto md:order-none md:mt-6 md:flex-1 md:flex-col md:px-3">
          {links.map(([to, label, icon]) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-2.5 whitespace-nowrap rounded-2xl px-3 py-2.5 text-sm font-medium transition ${
                  isActive ? 'bg-white text-ink shadow-sm' : 'text-white/70 hover:bg-white/10 hover:text-white'
                }`
              }
            >
              <Icon name={icon} className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
          {user?.role !== 'user' && (
            <Link to="/advisor" className="whitespace-nowrap rounded-2xl border border-white/15 px-3 py-2.5 text-sm text-white/75 hover:bg-white/10">顾问工作台</Link>
          )}
          {user?.role === 'admin' && (
            <>
              <Link to="/admin/packages" className="whitespace-nowrap rounded-2xl px-3 py-2.5 text-sm text-white/70 hover:bg-white/10">套餐管理</Link>
              <Link to="/admin/orders" className="whitespace-nowrap rounded-2xl px-3 py-2.5 text-sm text-white/70 hover:bg-white/10">额度管理</Link>
              <Link to="/admin/accounts" className="whitespace-nowrap rounded-2xl px-3 py-2.5 text-sm text-white/70 hover:bg-white/10">账号清理</Link>
              <Link to="/admin/system" className="whitespace-nowrap rounded-2xl px-3 py-2.5 text-sm text-white/70 hover:bg-white/10">系统状态</Link>
            </>
          )}
        </nav>
        <div className="ml-auto flex items-center gap-3 md:ml-0 md:mt-auto md:w-full md:border-t md:border-white/10 md:p-4">
          <span className="hidden h-9 w-9 shrink-0 place-items-center rounded-full bg-white/10 text-sm font-semibold md:grid">{initials}</span>
          <div className="hidden min-w-0 md:block">
            <p className="truncate text-sm font-medium">{user?.display_name}</p>
            <p className="truncate text-xs text-white/40">{user?.email}</p>
          </div>
          <button onClick={logout} className="inline-flex items-center gap-1.5 text-sm text-white/55 hover:text-white">
            <Icon name="logout" className="h-3.5 w-3.5" />
            退出登录
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-5 md:p-8 lg:p-10">
        <div className="mx-auto w-full max-w-5xl">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
