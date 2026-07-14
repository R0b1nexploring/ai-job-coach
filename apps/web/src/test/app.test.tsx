import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import App from '../app/App'
import { AuthProvider } from '../app/AuthContext'

function renderApp(path='/'){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><AuthProvider><App/></AuthProvider></MemoryRouter></QueryClientProvider>)}
test('首页显示价值主张和健康状态',async()=>{vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url.includes('/health')?{status:'ok'}:{error:{message:'未登录'}}),{status:url.includes('/health')?200:401,headers:{'Content-Type':'application/json'}})));renderApp('/');expect(screen.getByText(/把求职变成/)).toBeInTheDocument();expect(await screen.findByText(/服务正常/)).toBeInTheDocument()})
test('未登录访问用户页面会跳转登录',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({error:{message:'请先登录'}}),{status:401,headers:{'Content-Type':'application/json'}})));renderApp('/app/dashboard');expect(await screen.findByText('欢迎回来')).toBeInTheDocument()})
test('登录表单校验中文错误',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:401})));renderApp('/login');const user=userEvent.setup();const email=await screen.findByLabelText('邮箱');await user.clear(email);await user.type(email,'bad');await user.click(screen.getByRole('button',{name:'登录'}));expect(await screen.findByText('请输入有效邮箱')).toBeVisible()})
