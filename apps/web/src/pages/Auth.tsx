import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { PublicHeader } from '../components/Layout'
import { useAuth } from '../app/AuthContext'

const schema = z.object({
  email: z.string().email('请输入有效邮箱'),
  password: z.string().min(8, '密码至少 8 位'),
  display_name: z.string().optional(),
})
type Form = z.infer<typeof schema>

export function AuthPage({ register = false }: { register?: boolean }) {
  const nav = useNavigate()
  const { refresh } = useAuth()
  const [error, setError] = useState('')
  const form = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: register ? {} : { email: 'user@example.test', password: 'ChangeMe123!' },
  })
  const submit = async (v: Form) => {
    setError('')
    try {
      await api(`/api/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify(v) })
      refresh()
      nav('/app/resume-studio')
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败')
    }
  }
  return (
    <>
      <PublicHeader />
      <main className="mx-auto grid max-w-5xl items-center gap-10 px-5 py-12 md:grid-cols-2 md:py-16">
        <div className="hidden md:block">
          <span className="badge">自助简历工作台</span>
          <h2 className="mt-4 text-4xl font-bold tracking-tight">一份岗位，两份简历</h2>
          <p className="mt-4 max-w-md text-black/60 leading-7">
            登录后直接进入工作台：分析岗位、生成求职版和蓝图 Plus，再导出面试指南。
          </p>
          <ul className="mt-8 space-y-3 text-sm text-black/65">
            <li className="flex gap-2"><span className="text-sage">01</span>粘贴职位描述</li>
            <li className="flex gap-2"><span className="text-sage">02</span>生成求职版与蓝图</li>
            <li className="flex gap-2"><span className="text-sage">03</span>导出并准备面试</li>
          </ul>
        </div>
        <div className="card mx-auto w-full max-w-md">
          <h1 className="text-3xl font-bold tracking-tight">{register ? '创建账号' : '欢迎回来'}</h1>
          <p className="mt-2 text-sm text-black/50">{register ? '创建后即可进入简历工作台。' : '使用邮箱登录，继续未完成的简历。'}</p>
          <form noValidate className="mt-8 space-y-4" onSubmit={form.handleSubmit(submit)}>
            {register && (
              <label>
                <span className="label">称呼</span>
                <input className="field" {...form.register('display_name')} />
              </label>
            )}
            <label>
              <span className="label">邮箱</span>
              <input className="field" type="email" {...form.register('email')} />
              <small className="text-red-600">{form.formState.errors.email?.message}</small>
            </label>
            <label>
              <span className="label">密码</span>
              <input className="field" type="password" {...form.register('password')} />
              <small className="text-red-600">{form.formState.errors.password?.message}</small>
            </label>
            {error && <p className="text-red-600" role="alert">{error}</p>}
            <button className="btn w-full py-3" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? '请稍候…' : register ? '注册并继续' : '登录'}
            </button>
          </form>
          <p className="mt-5 text-sm text-black/60">
            {register ? '已有账号？' : '还没有账号？'}{' '}
            <Link className="font-semibold text-sage underline-offset-2 hover:underline" to={register ? '/login' : '/register'}>
              {register ? '登录' : '立即注册'}
            </Link>
          </p>
        </div>
      </main>
    </>
  )
}
