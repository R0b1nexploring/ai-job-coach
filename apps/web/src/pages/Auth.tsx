import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { PublicHeader } from '../components/Layout'
import { useAuth } from '../app/AuthContext'

const schema=z.object({email:z.string().email('请输入有效邮箱'),password:z.string().min(8,'密码至少 8 位'),display_name:z.string().optional()})
type Form=z.infer<typeof schema>
export function AuthPage({register=false}:{register?:boolean}){const nav=useNavigate(),{refresh}=useAuth(),[error,setError]=useState('');const form=useForm<Form>({resolver:zodResolver(schema),defaultValues:register?{}:{email:'user@example.test',password:'ChangeMe123!'}});const submit=async(v:Form)=>{setError('');try{await api(`/api/auth/${register?'register':'login'}`,{method:'POST',body:JSON.stringify(v)});refresh();nav('/app/resume-studio')}catch(e){setError(e instanceof Error?e.message:'请求失败')}};return <><PublicHeader/><main className="mx-auto max-w-md px-5 py-12"><div className="card"><h1 className="text-3xl font-black">{register?'创建账号':'欢迎回来'}</h1><form noValidate className="mt-8 space-y-4" onSubmit={form.handleSubmit(submit)}>{register&&<label><span className="label">称呼</span><input className="field" {...form.register('display_name')}/></label>}<label><span className="label">邮箱</span><input className="field" type="email" {...form.register('email')}/><small className="text-red-600">{form.formState.errors.email?.message}</small></label><label><span className="label">密码</span><input className="field" type="password" {...form.register('password')}/><small className="text-red-600">{form.formState.errors.password?.message}</small></label>{error&&<p className="text-red-600" role="alert">{error}</p>}<button className="btn w-full" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting?'请稍候…':register?'注册并继续':'登录'}</button></form><p className="mt-5 text-sm text-black/60">{register?'已有账号？':'还没有账号？'} <Link className="text-sage underline" to={register?'/login':'/register'}>{register?'登录':'立即注册'}</Link></p></div></main></>}
