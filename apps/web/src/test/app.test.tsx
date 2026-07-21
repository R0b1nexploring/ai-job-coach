import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import App from '../app/App'
import { AuthProvider } from '../app/AuthContext'

function renderApp(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter></QueryClientProvider>)
}

const coachResult = {
  job: { id: 'j1', title: '设备工程师', company_name: '虚构设备公司', city: '杭州', responsibilities: ['负责设备点检'], must_have: ['机械工程本科'], nice_to_have: ['有设备维护经验'], keywords: ['CAD'], work_conditions: ['可能需要轮班'], uncertain_fields: ['轮班安排'] },
  tailored_resume: { id: 'v1', title: '虚构设备公司 - 设备工程师', guard_status: 'passed', content: { headline: '设备工程师方向求职简历', sections: [{ name: '项目经历', items: [{ text: '使用 CAD 完成机械机构设计', source_fact_ids: ['f1'], target_requirement_ids: ['CAD'], new_claims: [] }] }], excluded_gaps: ['设备点检'] } },
  interview_guide: { questions: [{ id: 'q1', category: 'resume_verification', question: '你在项目中的职责是什么？', why_asked: '核实个人贡献', rubric: ['职责清晰'], follow_ups: [] }], self_introduction: { duration_seconds: 90, text: '您好，我应聘设备工程师。', source_fact_ids: ['f1'] }, project_answers: [{ question: '请介绍项目', answer: '按真实背景和行动说明。', source_fact_ids: ['f1'], follow_ups: ['遇到什么困难？'] }], common_answers: [{ question: '为什么选择这个岗位？', answer: '结合真实经历说明岗位动机。', source_fact_ids: ['f1'], follow_ups: [] }], preparation_plan: ['核对 JD 与原简历'], risk_reminders: ['不要补造数字'] },
  ocr_provider: 'rapidocr',
  notices: ['生成内容是建议稿，请逐项核对。'],
}

test('首页直接展示上传区且右上角只有登录入口', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { message: '未登录' } }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
  renderApp('/')
  expect(screen.getByRole('heading', { name: /上传简历和 JD 截图/ })).toBeVisible()
  expect(screen.getByText('上传你的简历')).toBeVisible()
  expect(screen.getByText('上传岗位 JD 截图')).toBeVisible()
  expect(await screen.findByRole('link', { name: '登录' })).toBeVisible()
  expect(screen.queryByText('套餐')).not.toBeInTheDocument()
  expect(screen.queryByText('投递')).not.toBeInTheDocument()
  expect(screen.queryByText('顾问工作台')).not.toBeInTheDocument()
})

test('旧工作台地址回到单页首页', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { message: '未登录' } }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
  renderApp('/app/dashboard')
  expect(await screen.findByRole('heading', { name: /上传简历和 JD 截图/ })).toBeVisible()
})

test('登录表单校验中文错误', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })))
  renderApp('/login')
  const user = userEvent.setup()
  const email = await screen.findByLabelText('邮箱')
  await user.clear(email)
  await user.type(email, 'bad')
  await user.click(screen.getByRole('button', { name: '登录' }))
  expect(await screen.findByText('请输入有效邮箱')).toBeVisible()
})

test('登录用户在同一页面得到定制简历和面试引导', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const body = url.endsWith('/api/auth/me')
      ? { id: 'u1', email: 'user@example.test', display_name: '测试用户', role: 'user', status: 'active' }
      : coachResult
    return new Response(JSON.stringify(body), { status: url.includes('/download') ? 200 : 201, headers: { 'Content-Type': 'application/json' } })
  }))
  renderApp('/')
  const user = userEvent.setup()
  const inputs = await screen.findAllByLabelText(/上传/)
  await user.upload(inputs[0], new File(['resume'], 'resume.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
  await user.upload(inputs[1], new File(['image'], 'jd.png', { type: 'image/png' }))
  await user.click(screen.getByRole('button', { name: '生成简历与面试建议' }))
  expect(await screen.findByText('虚构设备公司 · 设备工程师')).toBeVisible()
  expect(screen.getByText('设备工程师方向求职简历')).toBeVisible()
  expect(screen.getByText('您好，我应聘设备工程师。')).toBeVisible()
  expect(screen.getByText(/可能需要轮班/)).toBeVisible()
  expect(screen.getByText(/轮班安排/)).toBeVisible()
  expect(screen.getByText('常见问题回答框架')).toBeVisible()
  expect(screen.getByText('结合真实经历说明岗位动机。')).toBeVisible()
  expect(screen.getByText('真实性提醒')).toBeVisible()
  expect(screen.getByText(/不要补造数字/)).toBeVisible()
  expect(screen.getByRole('link', { name: '下载 DOCX' })).toHaveAttribute('href', '/api/coach/resume-versions/v1/download')
})
