import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../app/App'
import { AuthProvider } from '../app/AuthContext'
import { InterviewGuides } from '../pages/InterviewGuides'
import { ResumeStudio } from '../pages/ResumeStudio'

const currentUser = { id: 'u1', email: 'a@example.test', display_name: '用户A', role: 'user', status: 'active' }

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPath(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider><App /></AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('普通用户主导航只保留工作台、指南和设置', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return json(currentUser)
    if (url.includes('/api/notifications')) return json({ unread_count: 0 })
    if (url.includes('/api/jobs')) return json({ items: [], total: 0 })
    if (url.includes('/api/resumes')) return json({ items: [], total: 0 })
    if (url.includes('/api/experience')) return json({ items: [], total: 0 })
    if (url.includes('/api/target-profiles')) return json({ items: [], total: 0 })
    return json({})
  }))
  renderPath('/app/resume-studio')
  expect(await screen.findByRole('link', { name: '工作台' })).toBeVisible()
  expect(screen.getByRole('link', { name: '面试指南' })).toBeVisible()
  expect(screen.getByRole('link', { name: '设置' })).toBeVisible()
  expect(screen.queryByRole('link', { name: '岗位' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '投递' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '学习' })).not.toBeInTheDocument()
})

test('旧岗位页仍可直接打开', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return json(currentUser)
    if (url.includes('/api/notifications')) return json({ unread_count: 0 })
    if (url.includes('/api/jobs')) return json({ items: [], total: 0 })
    if (url.includes('/api/resumes')) return json({ items: [], total: 0 })
    if (url.includes('/api/campus-announcements')) return json({ items: [], total: 0 })
    return json({ items: [], total: 0 })
  }))
  renderPath('/app/jobs')
  expect(await screen.findByRole('heading', { name: /岗位|简章|发现/ })).toBeTruthy()
})

test('工作台默认只展示必要输入，附加素材按需展开', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ items: [], total: 0, unread_count: 0 })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  expect(await screen.findByText('你想申请什么岗位？')).toBeVisible()
  expect(screen.getByText('让结果更像你')).toBeVisible()
  expect(screen.getByText('生成你的两份简历')).toBeVisible()
  expect(screen.getByText('导出简历')).toBeVisible()
  expect(screen.getByText('准备面试')).toBeVisible()
  expect(screen.getByPlaceholderText(/粘贴职位描述/)).toBeVisible()
  expect(screen.getByText('上传现有简历')).toBeVisible()
  expect(screen.queryByPlaceholderText(/学校实验室/)).not.toBeInTheDocument()
  expect(screen.queryByText('示例生物工程')).not.toBeInTheDocument()
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '补充一段经历' }))
  expect(screen.getByPlaceholderText(/学校实验室/)).toBeVisible()
  expect(screen.getByPlaceholderText(/用自己的话描述/)).toBeVisible()
})

test('保存 JD 不会把原文写进画像 job_ids', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/jobs') && init?.method === 'POST') {
      return json({ id: 'job-saved', title: '目标岗位', company_name: '目标公司' }, 201)
    }
    if (url.endsWith('/api/jobs/import-text')) {
      return json({ id: 'job-saved', title: '目标岗位', company_name: '目标公司', raw_jd: '负责机械结构设计' }, 201)
    }
    if (url.endsWith('/api/target-profiles') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body || '{}'))
      expect(body.job_ids).toEqual(['job-saved'])
      expect(body.job_ids.join('')).not.toContain('负责机械')
      return json({ id: 'p1', title: '目标岗位', mode: 'single_jd' }, 201)
    }
    if (url.endsWith('/api/jobs')) return json({ items: [{ id: 'job-saved', title: '目标岗位', company_name: '目标公司' }], total: 1 })
    if (url.endsWith('/api/resumes')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/target-profiles')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/resume-bundles')) return json({ items: [], total: 0 })
    return json({ items: [], total: 0 })
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  await user.type(await screen.findByPlaceholderText(/粘贴职位描述/), '负责机械结构设计。\n要求熟悉 SolidWorks。')
  await user.click(screen.getByRole('button', { name: '分析这个岗位' }))
  expect(await screen.findByText('岗位已分析，可以直接生成简历。')).toBeVisible()
})

test('无旧简历也可生成，并轮询 queued 状态', async () => {
  let bundleReads = 0
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/jobs')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/resumes')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience')) {
      return json({
        items: [{ id: 'e1', title: '装配体课程设计', kind: 'project', status: 'confirmed', is_own: true, organization: '实验室', role_title: '学生', summary: '建模', details_json: {}, clarifications_json: [] }],
        total: 1,
      })
    }
    if (url.endsWith('/api/target-profiles')) return json({ items: [{ id: 'p1', title: '机械工程师', mode: 'single_jd' }], total: 1 })
    if (url.endsWith('/api/resume-bundles') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body || '{}'))
      expect(body.base_resume_id).toBeUndefined()
      return json({ id: 'b1', status: 'queued', versions: {}, guides: {}, can_retry: true }, 202)
    }
    if (url.includes('/api/resume-bundles/b1')) {
      bundleReads += 1
      if (bundleReads < 2) return json({ id: 'b1', status: 'queued', versions: {}, guides: {}, can_retry: true })
      return json({
        id: 'b1',
        status: 'ready',
        versions: { submittable: { id: 'v1', kind: 'submittable', status: 'passed', content_hash: 'h1' } },
        guides: { submittable: { id: 'g1', status: 'ready' } },
      })
    }
    if (url.includes('/studio')) {
      return json({
        id: 'v1',
        kind: 'submittable',
        title: '真实能力',
        guard_status: 'passed',
        content_hash: 'h1',
        quality_report_json: { status: 'passed', reviewer: 'model', reviewer_note: '模型评审（mock）' },
        content_json: {
          kind: 'submittable',
          factuality_policy: 'ai_expansion',
          headline: '机械工程师',
          sections: [{ name: '项目/科研/竞赛', items: [{ bullets: [{ id: 'b-lock', text: '完成装配体', achieved: false, locked: false, source_fact_ids: [], verification_status: 'ai_generated' }] }] }],
        },
      })
    }
    return json({ items: [], total: 0 })
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: 10 } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  const generateButton = await screen.findByRole('button', { name: '生成求职版和蓝图 Plus' })
  await waitFor(() => expect(generateButton).toBeEnabled())
  await user.click(generateButton)
  expect(await screen.findByText(/已排队生成/)).toBeVisible()
  expect(await screen.findByText('完成装配体', undefined, { timeout: 4000 })).toBeVisible()
  expect(screen.getByTitle('A4 简历预览')).toHaveAttribute(
    'src',
    expect.stringContaining('/api/resume-versions/v1/studio-preview'),
  )
  expect(screen.queryByText(/待核验/)).not.toBeInTheDocument()
})

test('模型降级会显示 degraded，失败可重试', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/jobs')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/resumes')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/target-profiles')) return json({ items: [{ id: 'p1', title: '机械工程师', mode: 'single_jd' }], total: 1 })
    if (url.endsWith('/api/resume-bundles') && init?.method === 'POST') {
      return json({ id: 'b-fail', status: 'queued', versions: {}, guides: {}, can_retry: true }, 202)
    }
    if (url.includes('/retry') && init?.method === 'POST') {
      return json({ id: 'b-fail', status: 'queued', versions: {}, guides: {}, can_retry: true }, 202)
    }
    if (url.includes('/api/resume-bundles/b-fail')) {
      return json({ id: 'b-fail', status: 'failed', error: '生成失败，请重试。', versions: {}, guides: {}, can_retry: true })
    }
    return json({ items: [], total: 0 })
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  const generateButton = await screen.findByRole('button', { name: '生成求职版和蓝图 Plus' })
  await waitFor(() => expect(generateButton).toBeEnabled())
  await user.click(generateButton)
  expect(await screen.findByText(/生成失败/)).toBeVisible()
  await user.click(screen.getByRole('button', { name: '重试生成' }))
  expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/retry'))).toBe(true)
})

test('锁定后整份重生成会发出重生成请求，非首条可局部重写', async () => {
  const lockRequests: Array<Record<string, unknown>> = []
  const regenerateRequests: Array<Record<string, unknown>> = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/jobs')) return json({ items: [{ id: 'j1', title: '机械工程师', company_name: '示例' }], total: 1 })
    if (url.endsWith('/api/resumes')) return json({ items: [{ id: 'r1', display_name: '我的简历' }], total: 1 })
    if (url.endsWith('/api/experience')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/target-profiles')) return json({ items: [{ id: 'p1', title: '机械工程师', mode: 'single_jd' }], total: 1 })
    if (url.endsWith('/api/resume-bundles') && init?.method === 'POST') {
      return json({
        id: 'b1',
        status: 'queued',
        versions: {},
        guides: {},
      }, 202)
    }
    if (url.includes('/api/resume-bundles/b1')) {
      return json({
        id: 'b1',
        status: 'ready',
        versions: { submittable: { id: 'v1', kind: 'submittable', status: 'passed', content_hash: 'h1' } },
        guides: { submittable: { id: 'g1', status: 'stale' } },
      })
    }
    if (url.includes('/api/resume-versions/v1/lock') && init?.method === 'POST') {
      lockRequests.push(JSON.parse(String(init.body || '{}')))
      return json({ id: 'v1', content_json: { headline: '机械工程师', sections: [] } })
    }
    if (url.includes('/regenerate') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body || '{}'))
      regenerateRequests.push(body)
      if (body.scope === 'bullet') expect(body.bullet_id).toBe('b-second')
      return json({ id: 'v1', content_json: { headline: '机械工程师', sections: [] }, quality_report_json: { status: 'passed' } })
    }
    if (url.includes('/interview-guides/g1/regenerate')) return json({ id: 'g1', status: 'ready' })
    if (url.includes('/studio')) {
      return json({
        id: 'v1',
        kind: 'submittable',
        title: '真实能力',
        guard_status: 'passed',
        quality_report_json: { status: 'passed' },
        content_json: {
          headline: '机械工程师',
          sections: [{
            name: '项目/科研/竞赛',
            items: [{
              bullets: [
                { id: 'b-first', text: '完成装配体', achieved: true, locked: false, source_fact_ids: ['f1'] },
                { id: 'b-second', text: '完成点检', achieved: true, locked: false, source_fact_ids: ['f2'] },
              ],
            }],
          }],
        },
      })
    }
    return json({ items: [], total: 0 })
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  const generateButton = await screen.findByRole('button', { name: '生成求职版和蓝图 Plus' })
  await waitFor(() => expect(generateButton).toBeEnabled())
  await user.click(generateButton)
  expect(await screen.findByText('完成点检')).toBeVisible()
  const rewriteButtons = screen.getAllByRole('button', { name: '重写本条' })
  await user.click(rewriteButtons[1])
  await user.click(screen.getAllByRole('button', { name: '锁定' })[0])
  expect(lockRequests[0]).toMatchObject({ bullet_id: 'b-first', locked: true })
  expect(await screen.findByText('锁定状态已保存并重新校验。')).toBeVisible()
  await user.click(screen.getByRole('button', { name: '整份重生成' }))
  expect(await screen.findByText('已重生成并重新校验。')).toBeVisible()
  expect(regenerateRequests).toContainEqual({ scope: 'all' })
  await user.click(screen.getByRole('button', { name: '重新生成指南' }))
  expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/interview-guides/g1/regenerate'))).toBe(true)
})

test('面试指南展示追问、六段式并提供下载', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/interview-guides/g1')) {
      return json({
        id: 'g1',
        kind: 'submittable',
        status: 'ready',
        practice_enabled: false,
        scoring_enabled: false,
        voice_enabled: false,
        content_json: {
          self_intro_60s: '60秒介绍',
          self_intro_90s: '90秒介绍',
          cards: [{
            bullet_id: 'b1',
            main_question: '请讲装配体',
            follow_ups: ['你本人做了哪一步？'],
            six_part_story: { context: '课程设计', action: '建模' },
            verification: '工程图',
          }],
        },
      })
    }
    return json({})
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/app/guides?guide=g1']}>
        <InterviewGuides />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('请讲装配体')).toBeVisible()
  expect(screen.getByText('连续追问')).toBeVisible()
  expect(screen.getByText('六段式讲法')).toBeVisible()
  expect(screen.getByText('90 秒自我介绍')).toBeVisible()
  expect(screen.getByText(/核验材料/)).toBeVisible()
  expect(screen.getByRole('link', { name: '下载指南' })).toHaveAttribute('href', '/api/interview-guides/g1/download')
})
