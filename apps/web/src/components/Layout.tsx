import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../app/AuthContext'

export function PublicHeader() {
  const { user, loading, refresh } = useAuth()
  const logout = async () => {
    await api('/api/auth/logout', { method: 'POST' })
    refresh()
  }
  return <header className="mx-auto flex max-w-5xl items-center justify-between px-5 py-6">
    <Link to="/" className="text-xl font-black tracking-tight">简历教练</Link>
    <div className="flex items-center gap-3 text-sm">
      {loading ? <span className="text-black/45">正在确认登录…</span> : user ? <>
        <span className="hidden text-black/55 sm:inline">{user.display_name}</span>
        <button className="font-semibold text-sage" onClick={logout}>退出</button>
      </> : <Link to="/login" className="font-semibold text-sage">登录</Link>}
    </div>
  </header>
}
