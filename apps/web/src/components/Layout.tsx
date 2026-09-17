import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
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
    <header className="sticky top-0 z-30 border-b border-line bg-canvas">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3">
        <Link to="/" className="text-ink"><Logo /></Link>
        <nav className="flex items-center gap-2 sm:gap-3">
          <Link to="/pricing" className="rounded-lg px-2.5 py-2 text-sm font-medium text-ink-secondary transition hover:bg-ink/[0.04] hover:text-ink">套餐</Link>
          <Link to="/login" className="hidden rounded-lg px-2.5 py-2 text-sm font-medium text-ink-secondary transition hover:bg-ink/[0.04] hover:text-ink sm:inline-flex">登录</Link>
          <Link to="/register" className="btn min-h-9 px-3.5 py-1.5 text-sm">免费开始</Link>
        </nav>
      </div>
    </header>
  )
}

export function AppLayout() {
  const { user, refresh } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
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
  const isFocusSurface = location.pathname === '/app/resume-studio' || location.pathname === '/app/guides'
  return (
    <div className="min-h-screen bg-cream md:flex">
      <aside className="app-navigation sticky top-0 z-30 flex flex-wrap items-center gap-x-2 border-b border-line bg-white px-3 py-2.5 text-ink md:h-screen md:w-[220px] md:flex-col md:flex-nowrap md:items-stretch md:border-b-0 md:border-r md:px-3 md:py-4">
        <Link to="/" className="px-1 text-ink md:px-2 md:py-1">
          <Logo />
        </Link>
        <p className="hidden text-[11px] font-medium uppercase tracking-[0.1em] text-ink-muted md:mt-8 md:block md:px-2">主要功能</p>
        <nav className="order-3 mt-2 flex w-full gap-1 overflow-x-auto md:order-none md:mt-2 md:flex-1 md:flex-col">
          {links.map(([to, label, icon]) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex min-h-10 items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium transition ${
                  isActive ? 'bg-sage/[0.09] text-sage' : 'text-ink-secondary hover:bg-ink/[0.035] hover:text-ink'
                }`
              }
            >
              <Icon name={icon} className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
          {user?.role !== 'user' && (
            <Link to="/advisor" className="whitespace-nowrap rounded-xl border border-line px-3 py-2.5 text-sm text-ink-secondary hover:bg-ink/[0.035]">顾问工作台</Link>
          )}
          {user?.role === 'admin' && (
            <>
              <Link to="/admin/packages" className="whitespace-nowrap rounded-xl px-3 py-2.5 text-sm text-ink-secondary hover:bg-ink/[0.035]">套餐管理</Link>
              <Link to="/admin/orders" className="whitespace-nowrap rounded-xl px-3 py-2.5 text-sm text-ink-secondary hover:bg-ink/[0.035]">额度管理</Link>
              <Link to="/admin/accounts" className="whitespace-nowrap rounded-xl px-3 py-2.5 text-sm text-ink-secondary hover:bg-ink/[0.035]">账号清理</Link>
              <Link to="/admin/system" className="whitespace-nowrap rounded-xl px-3 py-2.5 text-sm text-ink-secondary hover:bg-ink/[0.035]">系统状态</Link>
            </>
          )}
        </nav>
        <div className="ml-auto flex items-center gap-2 md:ml-0 md:mt-auto md:w-full md:rounded-xl md:border md:border-line md:bg-ink/[0.018] md:p-2.5">
          <span className="hidden h-8 w-8 shrink-0 place-items-center rounded-lg bg-sage/10 text-sm font-semibold text-sage md:grid">{initials}</span>
          <div className="hidden min-w-0 md:block">
            <p className="truncate text-xs font-semibold">{user?.display_name}</p>
            <p className="truncate text-[11px] text-ink-muted">未读 {notifications.data?.unread_count ?? 0}</p>
          </div>
          <button onClick={logout} className="ml-auto inline-grid h-8 w-8 place-items-center rounded-lg text-ink-muted transition hover:bg-ink/5 hover:text-ink" aria-label="退出登录" title="退出登录">
            <Icon name="logout" className="h-3.5 w-3.5" />
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-5 sm:px-5 md:px-7 md:py-7">
        <div className={`mx-auto w-full ${isFocusSurface ? 'max-w-[1540px]' : 'max-w-5xl'}`}>
          <Outlet />
        </div>
      </main>
    </div>
  )
}
