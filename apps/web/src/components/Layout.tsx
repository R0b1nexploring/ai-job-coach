import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../app/AuthContext'
import { useQuery } from '@tanstack/react-query'
import { clearOnboardingDraft } from '../utils/onboardingDraft'

const links = [['/app/resume-studio','工作台'],['/app/guides','面试指南'],['/app/settings','设置']]
export function PublicHeader(){return <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5"><Link to="/" className="text-xl font-black">求职罗盘</Link><nav className="flex items-center gap-4"><Link to="/pricing">套餐</Link><Link to="/login" className="btn-secondary">登录</Link></nav></header>}
export function AppLayout(){
  const {user,refresh}=useAuth(); const navigate=useNavigate()
  const notifications=useQuery({queryKey:['notifications'],queryFn:()=>api<{unread_count:number}>('/api/notifications'),enabled:!!user})
  const logout=async()=>{try{await api('/api/auth/logout',{method:'POST'});refresh();navigate('/')}finally{clearOnboardingDraft(user?.id)}}
  return <div className="min-h-screen md:flex"><aside className="bg-ink p-5 text-white md:min-h-screen md:w-64"><Link to="/" className="text-xl font-black">求职罗盘</Link><p className="mt-2 text-sm text-white/60">{user?.display_name} · 未读 {notifications.data?.unread_count??0}</p><nav className="mt-8 grid grid-cols-3 gap-2 md:grid-cols-1">{links.map(([to,label])=><NavLink key={to} to={to} className={({isActive})=>`rounded-xl px-3 py-2 ${isActive?'bg-white text-ink':'text-white/70 hover:bg-white/10'}`}>{label}</NavLink>)}</nav>{user?.role!=='user'&&<Link to="/advisor" className="mt-5 block rounded-xl border border-white/30 px-3 py-2">顾问工作台</Link>}{user?.role==='admin'&&<><Link to="/admin/packages" className="mt-2 block rounded-xl border border-white/30 px-3 py-2">套餐管理</Link><Link to="/admin/orders" className="mt-2 block rounded-xl border border-white/30 px-3 py-2">额度管理</Link><Link to="/admin/accounts" className="mt-2 block rounded-xl border border-white/30 px-3 py-2">账号清理</Link><Link to="/admin/system" className="mt-2 block rounded-xl border border-white/30 px-3 py-2">系统状态</Link></>}<button onClick={logout} className="mt-5 text-sm text-white/60">退出登录</button></aside><main className="min-w-0 flex-1 p-5 md:p-8"><Outlet/></main></div>
}
