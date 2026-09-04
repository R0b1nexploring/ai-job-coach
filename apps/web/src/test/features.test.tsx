import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import { api } from '../api/client'
import { Jobs, MatchDetail } from '../pages/Jobs'
import { Advisor } from '../pages/Advisor'
import { Applications, Interviews } from '../pages/Workflow'
import { AdminAccounts, AdminPackages, AdminSystem } from '../pages/Admin'
import { CapabilityTargets } from '../pages/CapabilityTargets'
import { Resumes } from '../pages/Resumes'
import { Channels } from '../pages/Channels'
import { Experience } from '../pages/Experience'

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
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/matches/')) return new Response(JSON.stringify(match), { status: 200, headers: { 'Content-Type': 'application/json' } })
    if (!init?.method && (url.endsWith('/api/resume-versions') || url.endsWith('/api/channels'))) {
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ error: { code: 'QUOTA_EXHAUSTED', message: 'resume 额度不足，请联系管理员发放演示额度。', details: {}, request_id: 'x' } }), { status: 409, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Routes><Route path="/app/matches/:id" element={<MatchDetail />} /></Routes>, '/app/matches/m1')
  const user = userEvent.setup()
  expect(await screen.findByRole('button', { name: '生成对照稿和可投递稿' })).toBeVisible()
  await user.click(await screen.findByRole('button', { name: '生成可投递简历' }))
  expect(await screen.findByText(/额度不足/)).toBeVisible()
})

test('API 错误保留后端中文消息', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'X', message: '可理解的中文错误', details: {}, request_id: 'x' } }), { status: 400, headers: { 'Content-Type': 'application/json' } })))
  await expect(api('/api/example')).rejects.toThrow('可理解的中文错误')
})

test('学习目标达成前必须填写证据并会写入事实库', async () => {
  let targetStatus = 'in_progress'
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/jobs')) {
      return new Response(JSON.stringify({ items: [{ id: 'j1', company_name: '示例公司', title: '设备工程师' }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (init?.method === 'PATCH') {
      const payload = JSON.parse(String(init.body))
      targetStatus = payload.status
      return new Response(JSON.stringify({ id: 't1', job_id: 'j1', requirement: '设备数据整理', deliverable: '完成巡检记录练习', acceptance_criteria_json: ['可独立查看'], estimated_hours: 8, severity: 'high', status: targetStatus, evidence_text: payload.evidence_text }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ items: [{ id: 't1', job_id: 'j1', requirement: '设备数据整理', deliverable: '完成巡检记录练习', acceptance_criteria_json: ['可独立查看'], estimated_hours: 8, severity: 'high', status: targetStatus, evidence_text: '' }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<CapabilityTargets />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '标记达成' }))
  await user.click(screen.getByRole('button', { name: '确认达成' }))
  expect(screen.getByText('请填写可核对的产出物证据。')).toBeVisible()
  await user.type(screen.getByLabelText('产出物证据'), '巡检记录.xlsx，可核对处理步骤')
  await user.click(screen.getByRole('button', { name: '确认达成' }))
  expect(await screen.findByText(/已加入事实库，可投递简历已更新/)).toBeVisible()
})

test('简历页明确区分蓝图和可投递版本', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const payload = url.endsWith('/api/resumes')
      ? { items: [], total: 0 }
      : { items: [
        { id: 'v1', job_id: 'j1', title: '设备工程师蓝图', kind: 'target', unachieved_count: 2, guard_status: 'passed', review_status: 'draft', content_json: { content_version: 2, kind: 'target', headline: '设备工程师', contact: {}, sections: [{ name: '项目经历', items: [{ organization: '示例大学', role_title: '课程项目', bullets: [{ text: '完成设备点检练习', achieved: false }] }] }], excluded_gaps: [] } },
        { id: 'v2', job_id: 'j1', title: '设备工程师投递版', kind: 'submittable', unachieved_count: 0, guard_status: 'passed', review_status: 'draft', content_json: { content_version: 2, kind: 'submittable', headline: '设备工程师', contact: {}, sections: [], excluded_gaps: [] } },
      ], total: 2 }
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Resumes />)
  expect(await screen.findByText('蓝图 · 对照 JD 的差距')).toBeVisible()
  expect(screen.getByText('可投递 · 全部已确认')).toBeVisible()
  expect(screen.getByText('2 条未达成，前往学习目标')).toBeVisible()
  expect(screen.getByText((_, node) => (node?.textContent || '').includes('完成设备点检练习') && node.tagName === 'LI')).toBeVisible()
})

test('蓝图投递只提示一次未达成目标', async () => {
  let applicationRequests = 0
  const queuedChannelIds: Array<string | null> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/matches/')) {
      return new Response(JSON.stringify(match), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.endsWith('/api/resume-versions')) {
      return new Response(JSON.stringify({ items: [{ id: 'v-target', base_resume_id: 'r1', job_id: 'j1', kind: 'target', unachieved_count: 1, guard_status: 'passed', review_status: 'approved', content_json: { sections: [{ items: [{ bullets: [{ text: '完成设备点检练习', achieved: false }] }] }] } }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.endsWith('/api/channels')) {
      return new Response(JSON.stringify({ items: [{ id: 'c1', company_name: '示例公司', channel_type: 'email', verify_status: 'unverified' }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.endsWith('/api/applications') && init?.method === 'POST') {
      applicationRequests += 1
      queuedChannelIds.push(JSON.parse(String(init.body)).channel_id)
      return new Response(JSON.stringify({ id: `a${applicationRequests}` }), { status: 201, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Routes><Route path="/app/matches/:id" element={<MatchDetail />} /></Routes>, '/app/matches/m1')
  const user = userEvent.setup()
  await user.selectOptions(await screen.findByLabelText('投递渠道'), 'c1')
  const queueButton = await screen.findByRole('button', { name: '加入投递队列' })
  await user.click(queueButton)
  const dialog = screen.getByRole('dialog', { name: '未达成目标投递提示' })
  expect(dialog).toBeVisible()
  expect(dialog.textContent).toMatch(/完成设备点检练习/)
  await user.click(screen.getByRole('button', { name: '继续投递' }))
  expect(await screen.findByText('已加入投递队列。')).toBeVisible()
  await user.click(queueButton)
  expect(screen.queryByRole('dialog', { name: '未达成目标投递提示' })).not.toBeInTheDocument()
  expect(applicationRequests).toBe(2)
  expect(queuedChannelIds).toEqual(['c1', 'c1'])
})

test('岗位库可选择白名单 JSON-LD 招聘页', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const payload = url.endsWith('/api/resumes')
      ? { items: [{ id: 'r1', display_name: '机械工程简历' }], total: 1 }
      : { items: [], total: 0 }
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Jobs />)
  const user = userEvent.setup()
  await screen.findByText('机械工程简历')
  await user.selectOptions(screen.getByLabelText('公开岗位来源'), 'public_jsonld')
  const input = screen.getByLabelText('公开招聘页 URL')
  const button = screen.getByRole('button', { name: '按简历发现岗位' })
  expect(input).toHaveAttribute('type', 'url')
  expect(button).toBeDisabled()
  await user.type(input, 'https://careers.example.com/jobs/123')
  expect(button).toBeEnabled()
})

test('投递渠道页展示公司入口和失效状态', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const payload = url.endsWith('/api/resumes')
      ? { items: [], total: 0 }
      : { items: [{ id: 'c1', company_name: '示例制造公司', channel_type: 'career_page', url: 'https://careers.example.com/jobs', email: '', scope: 'both', verify_status: 'unverified', source_updated_at: '2026-08-01T00:00:00Z' }], total: 1 }
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Channels />)
  expect(await screen.findByText('示例制造公司')).toBeVisible()
  expect(screen.getByText('公司招聘页 · 校招与社招')).toBeVisible()
  expect(screen.getByRole('link', { name: '打开投递入口' })).toHaveAttribute('href', 'https://careers.example.com/jobs')
  expect(screen.getByRole('button', { name: '读取公开岗位' })).toBeDisabled()
})

test('邮件渠道投递记录可以生成只读草稿', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/applications') && !init?.method) {
      return new Response(JSON.stringify({ items: [{ id: 'a1', status: 'ready_to_apply', channel_id: 'c1' }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.endsWith('/api/channels')) {
      return new Response(JSON.stringify({ items: [{ id: 'c1', company_name: '示例公司', channel_type: 'email', email: 'jobs@example.com', url: '' }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ to: 'jobs@example.com', subject: '应聘设备工程师 - 小陈', body: '您好。\n\n• 完成机械设计。\n\n感谢审阅。', attachment_hint: '请手动附加简历', mailto_url: 'mailto:jobs@example.com', warnings: ['系统不会代发邮件。'] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Applications />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '生成邮件草稿' }))
  expect(await screen.findByRole('dialog', { name: '邮件草稿' })).toBeVisible()
  expect(screen.getByDisplayValue('应聘设备工程师 - 小陈')).toBeVisible()
    expect(screen.getByText(/系统不会代发邮件/)).toBeVisible()
  expect(screen.getByRole('link', { name: '在邮件客户端打开' })).toHaveAttribute('href', 'mailto:jobs@example.com')
})

test('待确认投递必须调用专用确认接口', async () => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    requests.push(`${init?.method || 'GET'} ${url}`)
    if (url.endsWith('/api/channels')) {
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.endsWith('/api/applications') && !init?.method) {
      return new Response(JSON.stringify({ items: [{ id: 'a1', status: 'pending_confirmation', channel_id: null }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ id: 'a1', status: 'preparing_resume' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))

  shell(<Applications />)
  await userEvent.setup().click(await screen.findByRole('button', { name: '确认加入投递准备' }))

  await waitFor(() => expect(requests).toContain('POST /api/applications/a1/confirm'))
  expect(requests).not.toContain('PATCH /api/applications/a1/status')
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

test('管理员可以处理用户主动提交的账号删除申请', async () => {
  let purged = false
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'POST' && url.includes('/purge')) {
      purged = true
      return new Response(JSON.stringify({ status: 'deleted' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ items: purged ? [] : [{ id: 'u1', display_name: '待删除用户', email: 'delete@example.test', updated_at: '2026-07-16T00:00:00Z' }], total: purged ? 0 : 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<AdminAccounts />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '执行清理' }))
  expect(await screen.findByText(/已完成清理/)).toBeVisible()
  expect(await screen.findByText(/没有待处理/)).toBeVisible()
})

test('管理员可以创建套餐', async () => {
  let packages: any[] = []
  vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') {
      packages = [{ id: 'p1', code: 'career_plus', name: '求职进阶版', price_cents: 39900, billing_period: 'once', resume_quota: 5, application_quota: 10, interview_quota: 2, features_json: ['定制简历'], is_active: true }]
      return new Response(JSON.stringify(packages[0]), { status: 201, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ items: packages, total: packages.length }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<AdminPackages />)
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('套餐代码'), 'career_plus')
  await user.type(screen.getByLabelText('套餐名称'), '求职进阶版')
  await user.click(screen.getByRole('button', { name: '创建套餐' }))
  expect(await screen.findByText('career_plus')).toBeVisible()
  expect(screen.getByRole('button', { name: '保存套餐' })).toBeVisible()
})

test('系统状态页显示真实 AI 配置缺口且不暴露密钥', async () => {
  const payload = { providers: { llm: { provider: 'compatible', operational: false, uses_fallback: true, missing_configuration: ['LLM_API_KEY'], notice: '失败会回退 Mock。' }, jobs: { operational: true, providers: ['sample', 'greenhouse'] }, storage: { provider: 'local', operational: true, notice: '本地私有存储。' }, payment: { provider: 'disabled', operational: true, notice: 'MVP-1 禁用真实支付。' } }, maintenance: { expired_user_count: 1, deletion_request_count: 2, stale_job_count: 3 } }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  shell(<AdminSystem />)
  expect(await screen.findByText('真实 AI 配置不完整')).toBeVisible()
  expect(screen.getByText(/LLM_API_KEY/)).toBeVisible()
  expect(screen.getByText(/待标记过期岗位/)).toBeVisible()
  expect(screen.queryByText(/gho_|sk-/)).not.toBeInTheDocument()
})

test('经历库可以添加实习并区分范本', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'POST' && url.endsWith('/api/experience')) {
      const payload = JSON.parse(String(init.body))
      return new Response(JSON.stringify({
        id: 'e1', kind: payload.kind, title: payload.title, organization: payload.organization,
        role_title: payload.role_title, location: '', start_date: '', end_date: '',
        summary: payload.summary, bullets_json: payload.bullets_json, skills_json: payload.skills_json,
        source: 'user_added', is_template: false, is_own: true, linked_to_facts: true,
      }), { status: 201, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({
      items: [
        { id: 't1', kind: 'internship', title: '设备点检与保养实习', organization: '示例智造装备股份有限公司', role_title: '设备实习工程师', location: '杭州', start_date: '2025-07', end_date: '2025-09', summary: '课程或实习范本', bullets_json: ['按点检表完成检查'], skills_json: ['设备点检'], source: 'template', is_template: true, is_own: false, linked_to_facts: false },
      ],
      total: 1,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Experience />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '全站范本' }))
  expect(await screen.findByText('设备点检与保养实习')).toBeVisible()
  expect(screen.getByRole('button', { name: '按此范本创建我的经历' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: '我的经历' }))
  await user.type(screen.getByPlaceholderText('标题，例如设备点检实习'), '我的点检实习')
  await user.type(screen.getByPlaceholderText('组织 / 学校 / 自主项目'), '自己实习过的工厂')
  await user.type(screen.getByPlaceholderText('这段经历你实际做了什么，不要写没做过的数字或工具。'), '完成指定工位点检。')
  await user.click(screen.getByRole('button', { name: '保存到经历库' }))
  expect(await screen.findByText('已加入经历库，并写入可匹配的事实。')).toBeVisible()
})

test('岗位库展示校招简章的公告和投递入口', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/campus-announcements')) {
      return new Response(JSON.stringify({
        items: [{
          id: 'a1', company_name: '示例智造装备股份有限公司', title: '2026 校园招聘简章',
          cities_json: ['杭州'], jobs_json: ['设备工程师'], majors_json: ['机械类'],
          announcement_url: 'https://example.test/campus/smart-equip', apply_url: '',
          apply_email: 'campus@example.test', apply_kind: 'email', expired: false, batch: '秋招',
          written_test: '有笔试', jobs: [{ id: 'j9', title: '设备工程师', company_name: '示例智造装备股份有限公司' }],
        }],
        total: 1, page: 1, page_size: 20,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  shell(<Jobs />)
  expect(await screen.findByText('示例智造装备股份有限公司')).toBeVisible()
  expect(screen.getByRole('link', { name: '公告链接' })).toHaveAttribute('href', 'https://example.test/campus/smart-equip')
  expect(screen.getByRole('button', { name: '复制邮箱' })).toBeVisible()
  expect(screen.getByRole('button', { name: '匹配「设备工程师」' })).toBeVisible()
})
