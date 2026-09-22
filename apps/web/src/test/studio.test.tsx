import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../app/App'
import { AuthProvider } from '../app/AuthContext'
import { InterviewGuides } from '../pages/InterviewGuides'
import { a4PreviewScale, bundleStageLabel, ResumeStudio } from '../pages/ResumeStudio'

const currentUser = { id: 'u1', email: 'a@example.test', display_name: '用户A', role: 'user', status: 'active' }

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

test('A4 预览只按容器缩小，不改变 A4 画布比例', () => {
  expect(a4PreviewScale(1200)).toBe(1)
  expect(a4PreviewScale(397)).toBeCloseTo(0.5)
  expect(a4PreviewScale(0)).toBe(1)
})

test('异步阶段使用用户可理解的名称', () => {
  expect(bundleStageLabel('writing')).toBe('正在组织内容')
  expect(bundleStageLabel('quality_check')).toBe('正在质量检查')
  expect(bundleStageLabel('unknown')).toBe('处理中')
})

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
  expect(screen.queryByRole('link', { name: '生成记录' })).not.toBeInTheDocument()
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

test('工作台默认只展示岗位输入，后续步骤按状态解锁', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ items: [], total: 0, unread_count: 0 })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  expect(await screen.findByText('你想申请什么岗位？')).toBeVisible()
  expect(screen.getByPlaceholderText(/粘贴职位描述/)).toBeVisible()
  expect(screen.getByRole('button', { name: /^01\s*岗位/ })).toHaveAttribute('aria-current', 'step')
  expect(screen.getByRole('button', { name: /素材/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /双版简历/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /导出与指南/ })).toBeDisabled()
  expect(screen.queryByPlaceholderText(/学校实验室/)).not.toBeInTheDocument()
  expect(screen.queryByText('示例生物工程')).not.toBeInTheDocument()
})

test('生成记录入口放在工作台内，不占用主导航', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ items: [], total: 0, unread_count: 0 })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('link', { name: /生成记录/ })).toHaveAttribute('href', '/app/history')
})

test('目标 JD 与投递入口固定在简历左侧，当前步骤操作保持独立', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/jobs') && !url.endsWith('/api/jobs/j1')) {
      return json({ items: [{ id: 'j1', title: '机械工程师', company_name: '示例制造', city: '杭州', source_url: '' }], total: 1 })
    }
    if (url.endsWith('/api/jobs/j1')) {
      return json({ id: 'j1', title: '机械工程师', company_name: '示例制造', city: '杭州', raw_jd: '负责机械结构设计和工程图纸维护。', source_url: '' })
    }
    if (url.endsWith('/api/resumes')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience-facts')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/target-profiles')) return json({ items: [{ id: 'p1', title: '机械工程师', mode: 'single_jd', job_ids: ['j1'], snapshot_json: {} }], total: 1 })
    if (url.endsWith('/api/resume-bundles')) return json({ items: [], total: 0 })
    return json({ items: [], total: 0 })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ResumeStudio />
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('heading', { name: '目标 JD' })).toBeVisible()
  expect(await screen.findByText('机械工程师')).toBeVisible()
  expect(screen.getByRole('heading', { name: '投递入口' })).toBeVisible()
  expect(screen.getByRole('button', { name: '投递入口（即将接入）' })).toBeDisabled()
  expect(await screen.findByRole('heading', { name: '让结果更像你' })).toBeVisible()
})

test('保存 JD 不会把原文写进画像 job_ids', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/jobs') && init?.method === 'POST') {
      return json({ id: 'job-saved', title: '目标岗位', company_name: '目标公司' }, 201)
    }
    if (url.endsWith('/api/jobs/import-text')) {
      const body = JSON.parse(String(init?.body || '{}'))
      expect(body).toEqual({ raw_jd: '负责机械结构设计。\n要求熟悉 SolidWorks。' })
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
  await user.click(screen.getByRole('button', { name: '只分析岗位' }))
  expect(await screen.findByText('岗位已分析，可以直接生成简历。')).toBeVisible()
})

test('空白建档可编辑素材、查看缺口并确认原子事实', async () => {
  let material = {
    id: 'e-blank',
    title: '装配体课程设计',
    kind: 'project',
    status: 'draft',
    is_own: true,
    is_template: false,
    linked_to_facts: false,
    organization: '校内实验室',
    role_title: '',
    summary: '完成装配体建模',
    bullets_json: [],
    skills_json: ['SolidWorks'],
    source: 'user_added',
    location: '',
    start_date: '',
    end_date: '',
    details_json: { project_type: '课程设计', actions: '完成装配体建模', tools: 'SolidWorks', results: '' },
    clarifications_json: [] as Array<{ field: string; question: string }>,
  }
  let confirmed = false
  const patches: Array<Record<string, unknown>> = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/jobs')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/resumes')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/target-profiles')) return json({ items: [{ id: 'p1', title: '机械工程师', mode: 'single_jd' }], total: 1 })
    if (url.endsWith('/api/resume-bundles')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience-facts')) {
      return json({
        items: confirmed ? [{ id: 'f-action', material_id: material.id, claim_type: 'action', label: material.title, value_json: { text: material.summary }, verification_status: 'user_confirmed' }] : [],
        total: confirmed ? 1 : 0,
      })
    }
    if (url.endsWith(`/api/experience/${material.id}`) && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body || '{}'))
      patches.push(body)
      material = { ...material, ...body, details_json: { ...material.details_json, ...(body.details_json || {}) }, status: 'draft' }
      return json(material)
    }
    if (url.endsWith(`/api/experience/${material.id}/clarifications`) && init?.method === 'POST') {
      material = { ...material, clarifications_json: [{ field: 'ownership', question: '这件事里你本人具体负责哪一段？' }] }
      return json(material)
    }
    if (url.endsWith(`/api/experience/${material.id}/confirm`) && init?.method === 'POST') {
      confirmed = true
      material = { ...material, status: 'confirmed', linked_to_facts: true }
      return json(material)
    }
    if (url.endsWith('/api/experience')) return json({ items: [material], total: 1 })
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
  const result = await screen.findByLabelText('装配体课程设计 结果')
  await user.type(result, '完成答辩并交付工程图')
  await user.click(screen.getByRole('button', { name: '保存修改' }))
  await waitFor(() => expect(patches[0]).toMatchObject({ details_json: { results: '完成答辩并交付工程图' } }))
  await user.click(screen.getByRole('button', { name: '查看缺口追问' }))
  expect(await screen.findByText('缺口追问')).toBeVisible()
  const ownership = screen.getByLabelText(/本人具体负责哪一段/)
  await user.type(ownership, '本人负责建模与工程图')
  await user.click(screen.getByRole('button', { name: '保存修改' }))
  await waitFor(() => expect(patches.at(-1)).toMatchObject({ details_json: { ownership: '本人负责建模与工程图' } }))
  await user.click(screen.getByRole('button', { name: '确认并生成原子事实' }))
  expect(await screen.findByText('素材已拆成原子事实并确认。')).toBeVisible()
  const confirmedSummary = await screen.findByText('装配体课程设计 · 已确认')
  await user.click(confirmedSummary)
  expect(await screen.findByText('已拆分的原子事实')).toBeVisible()
  expect(screen.getByText(/完成装配体建模 · 已确认/)).toBeVisible()
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
        quality_report_json: {
          status: 'passed',
          reviewer: 'model',
          reviewer_note: '模型评审（mock）',
          recommendations: [{ bullet_id: 'b-lock', suggestion: '补充验证方式' }],
          star_diagnostics: [{ field: 'actions.0.rationale', message: '缺少取舍' }],
          issues: ['内部质量问题'],
        },
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

test('一次点击即可保存岗位并开始生成双版本', async () => {
  const calls: string[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method || 'GET'
    if (url.endsWith('/api/jobs') && method === 'GET') return json({ items: [], total: 0 })
    if (url.endsWith('/api/resumes')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience-facts')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/target-profiles') && method === 'GET') return json({ items: [], total: 0 })
    if (url.endsWith('/api/jobs/import-text')) {
      calls.push('import')
      return json({ id: 'j1', company_name: '示例公司', title: '机械设计工程师', raw_jd: '负责机械结构设计' })
    }
    if (url.endsWith('/api/target-profiles') && method === 'POST') {
      calls.push('profile')
      return json({ id: 'p-first', title: '机械设计工程师', mode: 'single_jd' })
    }
    if (url.endsWith('/api/resume-bundles') && method === 'POST') {
      calls.push('bundle')
      return json({ id: 'b-first', status: 'queued', versions: {}, guides: {}, can_retry: true }, 202)
    }
    if (url.includes('/api/resume-bundles/b-first')) {
      return json({
        id: 'b-first',
        status: 'ready',
        versions: { submittable: { id: 'v-first', kind: 'submittable', status: 'passed', content_hash: 'h' } },
        guides: { submittable: { id: 'g-first', status: 'ready' } },
      })
    }
    if (url.includes('/studio')) {
      return json({
        id: 'v-first', kind: 'submittable', title: '真实能力', guard_status: 'passed', content_hash: 'h',
        quality_report_json: { status: 'passed' },
        content_json: {
          kind: 'submittable', factuality_policy: 'ai_expansion', headline: '机械设计工程师',
          sections: [{ name: '项目/科研/竞赛', items: [{ bullets: [{ id: 'b1', text: '完成装配体', achieved: false, locked: false, source_fact_ids: [], verification_status: 'ai_generated' }] }] }],
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
  const jd = await screen.findByPlaceholderText(/粘贴职位描述/)
  await user.type(jd, '负责机械结构设计')
  await user.click(screen.getByRole('button', { name: /生成我的简历/ }))
  expect(await screen.findByText(/已保存岗位并开始生成/)).toBeVisible()
  expect(calls).toEqual(['import', 'profile', 'bundle'])
})


test('模型异常后的降级版本不向用户暴露内部降级原因', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/jobs')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/resumes')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/experience-facts')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/target-profiles')) return json({ items: [], total: 0 })
    if (url.endsWith('/api/resume-bundles')) return json({ items: [{ id: 'b-degraded', status: 'degraded' }], total: 1 })
    if (url.endsWith('/api/resume-bundles/b-degraded')) {
      return json({
        id: 'b-degraded',
        status: 'degraded',
        versions: {},
        guides: {},
        generation_metadata_json: {
          degraded: true,
          degraded_reason: '模型不可用，已使用确定性检查并通过硬门禁。',
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
  // The bundle still loads as a deliverable, but the internal degraded reason
  // and reviewer diagnostics stay off the user-facing workspace (task 15.20).
  await waitFor(() => expect(screen.queryByText(/模型不可用/)).not.toBeInTheDocument())
  expect(screen.queryByText(/降级/)).not.toBeInTheDocument()
})

test('生成失败会显示原因并可重试', async () => {
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
  // The workspace reports deliverability, not the internal quality verdict.
  expect(screen.queryByText('已通过')).not.toBeInTheDocument()
  expect(screen.queryByText('降级可用')).not.toBeInTheDocument()
  // Critic scores, STAR diagnostics and repair history stay internal (15.20).
  expect(screen.queryByText('模型评审（mock）')).not.toBeInTheDocument()
  expect(screen.queryByText('补充验证方式')).not.toBeInTheDocument()
  expect(screen.queryByText(/缺少取舍/)).not.toBeInTheDocument()
  expect(screen.queryByText('内部质量问题')).not.toBeInTheDocument()
  expect(screen.getAllByText('已关联 1 条素材事实')).toHaveLength(2)
  expect(screen.queryByText('来源 f1')).not.toBeInTheDocument()
  const rewriteButtons = screen.getAllByRole('button', { name: '重写本条' })
  await user.click(rewriteButtons[1])
  await user.click(screen.getAllByRole('button', { name: '锁定' })[0])
  expect(lockRequests[0]).toMatchObject({ bullet_id: 'b-first', locked: true })
  expect(await screen.findByText('锁定状态已保存并重新校验。')).toBeVisible()
  await user.click(screen.getByRole('button', { name: '整份重生成' }))
  expect(await screen.findByText('已重生成并重新校验。')).toBeVisible()
  expect(regenerateRequests).toContainEqual({ scope: 'all' })
  await user.click(screen.getByRole('button', { name: /导出与指南/ }))
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
          project_cards: [{
            project_id: 'p1',
            title: '装配体课程设计',
            star_outline: {
              situation: { context: '课程设计', problem: '需要完成装配验证' },
              task: { role: '负责人', goal: '输出工程图' },
              actions: [{ step: '拆分装配', method: 'SolidWorks', rationale: '便于校核', difficulty: '尺寸配合' }],
              result: { deliverables: ['工程图'], verification_method: '装配检查' },
            },
            main_question: '请用 STAR 说明装配体课程设计。',
            follow_up_chains: [{ question: '为什么选择 SolidWorks？', follow_ups: ['如何校核尺寸？'], intent: '确认技术取舍', required_evidence: '工程图', common_mistakes: '只报工具名' }],
            result_verification: '用工程图与装配检查核验。',
            knowledge_preparation: ['复盘配合公差'],
            practice_steps: ['90 秒完整讲述'],
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
  expect(screen.getByText('要点 01')).toBeVisible()
  expect(screen.getByText('已就绪')).toBeVisible()
  expect(screen.getByText('连续追问')).toBeVisible()
  expect(screen.getByText('六段式讲法')).toBeVisible()
  expect(screen.getByRole('heading', { name: '90 秒自我介绍' })).toBeVisible()
  expect(screen.getByText(/核验材料/)).toBeVisible()
  expect(screen.getAllByText('项目 STAR 讲述').length).toBeGreaterThan(0)
  expect(screen.getByText('装配体课程设计')).toBeVisible()
  expect(screen.getByText('项目连续追问')).toBeVisible()
  expect(screen.getByText('知识准备')).toBeVisible()
  expect(screen.queryByText('p1')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: '下载指南' })).toHaveAttribute('href', '/api/interview-guides/g1/download')
})
