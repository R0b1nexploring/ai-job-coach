import path from 'node:path'
import { test, expect } from '@playwright/test'

test('用户在单页完成简历和 JD 截图优化', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /上传简历和 JD 截图/ })).toBeVisible()
  await expect(page.getByRole('link', { name: '登录' })).toBeVisible()
  await expect(page.getByText('投递')).toHaveCount(0)
  await expect(page.getByText('套餐')).toHaveCount(0)

  await page.getByRole('link', { name: '登录' }).click()
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('button', { name: '生成简历与面试建议' })).toBeVisible()

  const jdBase64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 1200
    canvas.height = 520
    const context = canvas.getContext('2d')!
    context.fillStyle = 'white'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.fillStyle = 'black'
    context.font = '42px sans-serif'
    const lines = [
      '设备工程师',
      '负责设备点检、维护和 CAD 图纸管理',
      '要求机械工程本科，熟悉 CAD',
      '能够与项目团队协作完成设备维护',
    ]
    lines.forEach((line, index) => context.fillText(line, 45, 80 + index * 100))
    return canvas.toDataURL('image/png').split(',')[1]
  })
  const uploads = page.locator('input[type="file"]')
  await uploads.nth(0).setInputFiles(path.resolve('../../data/samples/sample_resume.docx'))
  await uploads.nth(1).setInputFiles({
    name: '虚构岗位JD.png',
    mimeType: 'image/png',
    buffer: Buffer.from(jdBase64, 'base64'),
  })
  await page.getByLabel('JD 文字补充').fill('虚构设备公司招聘设备工程师，工作地点杭州。')
  await page.getByRole('button', { name: '生成简历与面试建议' }).click()

  await expect(page.getByText('虚构设备公司 · 设备工程师')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: '建议稿，请逐项核对' })).toBeVisible()
  await expect(page.getByText(/约 90 秒自我介绍草稿/)).toBeVisible()
  await expect(page.getByText('围绕真实经历准备回答')).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载 DOCX' }).click()
  expect((await download).suggestedFilename()).toMatch(/tailored-resume-\d{8}\.docx/)
})
