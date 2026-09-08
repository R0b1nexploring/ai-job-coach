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
  await page.getByRole('button', { name: '分析这个岗位' }).click()
  await expect(page.getByText('岗位已分析，可以直接生成简历。')).toBeVisible()

  await expect(page.getByPlaceholder(/学校实验室/)).toHaveCount(0)
  await page.getByRole('button', { name: '补充一段经历' }).click()
  await page.getByPlaceholder(/学校实验室/).fill('用户自己的实验室')
  await page.getByPlaceholder(/用自己的话描述/).fill('我使用 SolidWorks 完成装配体建模并输出工程图。')
  await page.getByPlaceholder(/完成答辩/).fill('输出工程图并完成答辩')
  await page.getByRole('button', { name: '保存这段经历' }).click()
  await expect(page.getByText('这段经历已加入生成参考。')).toBeVisible()

  await page.getByRole('button', { name: '生成求职版和蓝图 Plus' }).click()
  await expect(page.getByTestId('a4-preview')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: '求职版', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '蓝图 Plus', exact: true })).toBeVisible()

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
  const pdf = await page.request.get(pdfHref || '')
  const health = await page.request.get('/api/health')
  expect(health.ok()).toBeTruthy()
  const pdfAvailable = (await health.json()).pdf_converter_available === true
  if (pdfAvailable) {
    expect(pdf.status()).toBe(200)
    expect(pdf.headers()['content-type']).toContain('pdf')
    expect((await pdf.body()).byteLength).toBeGreaterThan(1000)
  } else {
    expect(pdf.status()).toBe(503)
    const body = await pdf.json()
    expect(body.error.code).toBe('PDF_CONVERTER_UNAVAILABLE')
  }

  await page.getByRole('link', { name: '求职版作战指南' }).click()
  await expect(page.getByRole('heading', { name: '面试指南' })).toBeVisible()
  await expect(page.locator('article.card').first()).toBeVisible()
  await page.goto('/app/resume-studio')
  await expect(page.getByRole('button', { name: '蓝图 Plus', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '蓝图 Plus', exact: true }).click()
  await page.getByRole('link', { name: '蓝图风险指南' }).click()
  await expect(page.getByRole('heading', { name: '面试指南' })).toBeVisible()
})
