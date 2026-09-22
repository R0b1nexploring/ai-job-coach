import { test, expect } from '@playwright/test'

test('新用户从粘贴 JD 走到双轨简历、导出和两份指南', async ({ page, request }) => {
  test.setTimeout(120_000)
  const email = `studio-${Date.now()}@example.test`
  const password = 'Password123!'
  const registered = await request.post('/api/auth/register', {
    data: { email, password, display_name: '新用户' },
  })
  expect(registered.ok()).toBeTruthy()
  const user = await registered.json()
  const admin = await request.post('/api/auth/login', {
    data: { email: 'admin@example.test', password: 'ChangeMe123!' },
  })
  expect(admin.ok()).toBeTruthy()
  const grant = await request.post('/api/admin/quotas/grant', {
    data: {
      user_id: user.id,
      quota_type: 'resume',
      amount: 5,
      reason: 'Playwright 新用户工作台验收',
      idempotency_key: `e2e-studio-${Date.now()}`,
    },
  })
  expect(grant.ok()).toBeTruthy()

  await page.goto('/login')
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: /求职简历/ })).toBeVisible()
  await expect(page.getByRole('link', { name: '工作台' })).toBeVisible()
  await expect(page.getByRole('link', { name: '面试指南' })).toBeVisible()
  await expect(page.getByRole('link', { name: '设置' })).toBeVisible()
  await expect(page.getByRole('link', { name: '岗位' })).toHaveCount(0)

  await page.getByPlaceholder(/粘贴职位描述/).fill('负责机械结构设计。\n要求熟悉 SolidWorks 并能输出装配体。')
  // The default first-run action saves the JD, builds the profile and queues
  // both versions in one click; the explicit analysis stays as a secondary step.
  await expect(page.getByRole('button', { name: /生成我的简历/ })).toBeVisible()
  await page.getByRole('button', { name: '只分析岗位' }).click()
  await expect(page.getByText('岗位已分析，可以直接生成简历。')).toBeVisible()
  await expect(page.getByRole('heading', { name: '目标 JD' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '投递入口' })).toBeVisible()
  await expect(page.getByRole('button', { name: '投递入口（即将接入）' })).toBeDisabled()

  await expect(page.getByPlaceholder(/学校实验室/)).toHaveCount(0)
  await page.getByRole('button', { name: '补充一段经历' }).click()
  await page.getByPlaceholder(/学校实验室/).fill('用户自己的实验室')
  await page.getByPlaceholder(/用自己的话描述/).fill('我使用 SolidWorks 完成装配体建模并输出工程图。')
  await page.getByPlaceholder(/完成答辩/).fill('输出工程图并完成答辩')
  await page.getByRole('button', { name: '保存这段经历' }).click()
  await expect(page.getByText(/空白素材已保存/)).toBeVisible()
  await page.getByRole('button', { name: '查看缺口追问' }).click()
  await expect(page.getByRole('heading', { name: '缺口追问' })).toBeVisible()
  await page.getByLabel(/本人具体负责哪一段/).fill('本人负责装配体建模与工程图输出')
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByText(/素材修改已保存/)).toBeVisible()
  await page.getByRole('button', { name: '确认并生成原子事实' }).click()
  await expect(page.getByText('素材已拆成原子事实并确认。')).toBeVisible()
  await page.locator('summary').filter({ hasText: '· 已确认' }).click()
  await expect(page.getByText('已拆分的原子事实')).toBeVisible()

  await page.getByRole('button', { name: '生成求职版和蓝图 Plus' }).click()
  await expect(page.getByTestId('a4-preview')).toBeVisible({ timeout: 60_000 })
  const desktopPreview = await page.getByTestId('a4-preview').boundingBox()
  expect(desktopPreview?.width).toBeLessThanOrEqual(794)
  await expect(page.getByRole('button', { name: '求职版', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '蓝图 Plus', exact: true })).toBeVisible()
  // The workspace shows the finished copy, not the internal quality verdict:
  // no critic score, STAR diagnostic, degraded reason or repair history.
  await expect(page.getByText('质量状态')).toHaveCount(0)
  await expect(page.getByText('可改进之处')).toHaveCount(0)
  await expect(page.getByText(/降级/)).toHaveCount(0)
  await expect(page.getByText(/模型评审/)).toHaveCount(0)

  // Deliverables live in the fourth workspace step in the progressive UI.
  await page.getByRole('button', { name: /导出与指南/ }).click()
  const htmlLink = page.getByRole('link', { name: '下载 HTML' })
  const docxLink = page.getByRole('link', { name: '下载 DOCX' })
  const pdfLink = page.getByRole('link', { name: '下载 PDF' })
  await expect(htmlLink).toBeVisible()
  await expect(docxLink).toBeVisible()
  const htmlHref = await htmlLink.getAttribute('href')
  const docxHref = await docxLink.getAttribute('href')
  const pdfHref = await pdfLink.getAttribute('href')
  const html = await page.request.get(htmlHref || '')
  const docx = await page.request.get(docxHref || '')
  expect(html.ok()).toBeTruthy()
  expect(docx.ok()).toBeTruthy()
  const [htmlDownload] = await Promise.all([
    page.waitForEvent('download'),
    htmlLink.click(),
  ])
  expect(htmlDownload.suggestedFilename()).toBe('resume.html')
  expect(await htmlDownload.path()).toBeTruthy()
  const [docxDownload] = await Promise.all([
    page.waitForEvent('download'),
    docxLink.click(),
  ])
  expect(docxDownload.suggestedFilename()).toBe('resume.docx')
  expect(await docxDownload.path()).toBeTruthy()
  const pdf = await page.request.get(pdfHref || '')
  const health = await page.request.get('/api/health')
  expect(health.ok()).toBeTruthy()
  const pdfAvailable = (await health.json()).pdf_converter_available === true
  if (pdfAvailable) {
    expect(pdf.status()).toBe(200)
    expect(pdf.headers()['content-type']).toContain('pdf')
    expect((await pdf.body()).byteLength).toBeGreaterThan(1000)
    const [pdfDownload] = await Promise.all([
      page.waitForEvent('download'),
      pdfLink.click(),
    ])
    expect(pdfDownload.suggestedFilename()).toBe('resume.pdf')
    expect(await pdfDownload.path()).toBeTruthy()
  } else {
    expect(pdf.status()).toBe(503)
    const body = await pdf.json()
    expect(body.error.code).toBe('PDF_CONVERTER_UNAVAILABLE')
  }

  await page.getByRole('link', { name: '求职版作战指南' }).click()
  await expect(page.getByRole('heading', { name: '面试指南' })).toBeVisible()
  await expect(page.locator('article.guide-block').first()).toBeVisible()
  await expect(page.getByText(/面向单 JD 岗位画像/).first()).toBeVisible()
  await expect(page.getByText(/SolidWorks|装配体建模/).first()).toBeVisible()
  await page.goto('/app/resume-studio')
  await expect(page.getByRole('button', { name: '蓝图 Plus', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '蓝图 Plus', exact: true }).click()
  await page.getByRole('button', { name: /导出与指南/ }).click()
  await page.getByRole('link', { name: '蓝图风险指南' }).click()
  await expect(page.getByRole('heading', { name: '面试指南' })).toBeVisible()
  await expect(page.locator('article.guide-block').first()).toBeVisible()
  await expect(page.locator('.guide-reader main').getByText('项目 STAR 讲述').first()).toBeVisible()
  // New project cards render the versioned practice structure.
  await expect(page.locator('.guide-reader main').getByText('项目用途').first()).toBeVisible()
  await expect(page.locator('.guide-reader main').getByText('操作步骤').first()).toBeVisible()
  await expect(page.locator('.guide-reader main').getByText('面试追问').first()).toBeVisible()
  await expect(page.getByText(/面向单 JD 岗位画像/).first()).toBeVisible()
  await expect(page.getByText(/SolidWorks|装配体建模/).first()).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/app/resume-studio')
  const narrowPreview = page.getByTestId('a4-preview')
  await expect(narrowPreview).toBeVisible()
  await expect.poll(async () => (await narrowPreview.boundingBox())?.width || 0).toBeLessThan(390)
  const narrowBox = await narrowPreview.boundingBox()
  expect(narrowBox?.height && narrowBox?.width).toBeTruthy()
  expect((narrowBox?.height || 0) / (narrowBox?.width || 1)).toBeCloseTo(1123 / 794, 1)
  await page.getByRole('button', { name: '关闭预览' }).click()
  await page.evaluate(() => window.scrollTo(0, 900))
  const navigationBox = await page.locator('.app-navigation').boundingBox()
  const stepsBox = await page.getByLabel('简历制作进度').boundingBox()
  expect(navigationBox && stepsBox).toBeTruthy()
  expect(stepsBox?.y || 0).toBeGreaterThanOrEqual((navigationBox?.height || 0) - 1)
})
