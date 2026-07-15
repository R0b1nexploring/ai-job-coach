import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import { api } from '../api/client'
import { MatchDetail } from '../pages/Jobs'
import { Advisor } from '../pages/Advisor'
import { Interviews } from '../pages/Workflow'

function shell(node: React.ReactNode, path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{node}</MemoryRouter></QueryClientProvider>)
}

const match = {
  id: 'm1', resume_id: 'r1', job_id: 'j1', total_score: 68, recommendation: '可以尝试',
  dimension_scores_json: { hard_requirements: 24, skills: 10, experience: 16, keywords: 6, preferences: 7, freshness: 5 },
  evidence_json: [], gaps_json: [{ requirement: '设备点检', action: '完成练习项目' }],
  confirmations_json: ['是否接受轮班'], ai_explanation_json: { summary: '专业匹配，维护证据较弱。' },
}

test('匹配报告展示六项分数、缺口和待确认项', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(match), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  shell(<Routes><Route path="/app/matches/:id" element={<MatchDetail />} /></Routes>, '/app/matches/m1')
  expect(await screen.findByText('六项评分')).toBeVisible()
  expect(screen.getByText('硬性条件')).toBeVisible()
  expect(screen.queryByText('hard_requirements')).not.toBeInTheDocument()
  expect(screen.getByText(/设备点检/)).toBeVisible()
  expect(screen.getByText('是否接受轮班')).toBeVisible()
})

test('额度不足错误转换为清晰中文提示', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/matches/')) return new Response(JSON.stringify(match), { status: 200, headers: { 'Content-Type': 'application/json' } })
    return new Response(JSON.stringify({ error: { code: 'QUOTA_EXHAUSTED', message: 'resume 额度不足，请联系管理员发放演示额度。', details: {}, request_id: 'x' } }), { status: 409, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Routes><Route path="/app/matches/:id" element={<MatchDetail />} /></Routes>, '/app/matches/m1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '生成定制简历' }))
  expect(await screen.findByText(/额度不足/)).toBeVisible()
})

test('API 错误保留后端中文消息', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'X', message: '可理解的中文错误', details: {}, request_id: 'x' } }), { status: 400, headers: { 'Content-Type': 'application/json' } })))
  await expect(api('/api/example')).rejects.toThrow('可理解的中文错误')
})

test('顾问九队列同时展示空状态和任务状态', async () => {
  const names = ['新线索','待咨询','待付款','待核实','待修改','待投递','有面试','待复盘','退款/争议']
  const queues = names.map((name, index) => ({ name, count: index === 4 ? 1 : 0, items: index === 4 ? [{ id: 'v1', user_id: 'user1', type: 'resume', risk: 'medium', next_action: '审核简历', can_review: true }] : [] }))
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ queues }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  shell(<Advisor />)
  expect(await screen.findByText('审核简历')).toBeVisible()
  expect(screen.getByRole('button', { name: '批准简历' })).toBeVisible()
  expect(screen.getAllByText('当前无任务')).toHaveLength(8)
})

test('用户可以填写模拟面试回答并提交顾问评分', async () => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    requests.push(`${init?.method || 'GET'} ${url}`)
    const json = url.endsWith('/api/jobs')
      ? { items: [{ id: 'j1', company_name: '虚构公司', title: '设备工程师' }] }
      : url.endsWith('/api/resume-versions')
        ? { items: [] }
        : url.endsWith('/api/interviews')
          ? { items: [{ id: 'i1', status: 'draft', question_set_json: { questions: [{ id: 'q1', question: '你负责了什么？', why_asked: '核实贡献', rubric: ['说明个人职责'] }], self_introduction: { duration_seconds: 90, text: '您好，我应聘设备工程师。', source_fact_ids: ['f1'] }, project_answers: [{ question: '介绍项目', answer: '按真实背景说明。', follow_ups: ['个人职责是什么？'] }], common_answers: [{ question: '为什么选择岗位？', answer: '结合 JD 回答。' }], preparation_plan: ['核对 JD'], risk_reminders: ['不要补造数字'] }, answers_json: {}, scorecard_json: {}, feedback_json: {} }] }
          : { id: 'i1', status: 'submitted' }
    return new Response(JSON.stringify(json), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Interviews />)
  const user = userEvent.setup()
  expect(await screen.findByText(/您好，我应聘设备工程师/)).toBeVisible()
  expect(screen.getByText('项目回答与追问')).toBeVisible()
  expect(screen.getByText('面试前准备')).toBeVisible()
  await user.type(await screen.findByLabelText('回答第 1 题'), '我负责整理点检记录。')
  await user.click(screen.getByRole('button', { name: '提交顾问评分' }))
  await screen.findByText(/你负责了什么/)
  expect(requests.some((request) => request === 'PATCH /api/interviews/i1/answers')).toBe(true)
  expect(requests.some((request) => request === 'POST /api/interviews/i1/submit')).toBe(true)
})

test('顾问可为已提交的模拟面试填写评分与复盘', async () => {
  const names = ['新线索','待咨询','待付款','待核实','待修改','待投递','有面试','待复盘','退款/争议']
  const queues = names.map((name) => ({ name, count: name === '待复盘' ? 1 : 0, items: name === '待复盘' ? [{ id: 'i1', user_id: 'user1', type: 'interview', risk: 'medium', next_action: '评分复盘', can_score: true }] : [] }))
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ queues }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  shell(<Advisor />)
  expect(await screen.findByLabelText('内容真实性')).toHaveValue(3)
  expect(screen.getByLabelText('复盘总结')).toBeVisible()
  expect(screen.getByRole('button', { name: '提交面试评分' })).toBeVisible()
})
