import { expect, test } from '@playwright/test'


test('管理员查看系统状态、账号清理并完成套餐 CRUD', async ({ page }) => {
  const code = `e2e_admin_${Date.now()}`
  await page.goto('/login')
  await page.getByLabel('邮箱').fill('admin@example.test')
  await page.getByLabel('密码').fill('ChangeMe123!')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: /求职简历|下一步/ })).toBeVisible()

  await page.goto('/admin/system')
  await expect(page.getByRole('heading', { name: '系统状态' })).toBeVisible()
  await expect(page.getByText('维护任务预览')).toBeVisible()
  await expect(page.getByText('AI Provider')).toBeVisible()

  await page.goto('/admin/accounts')
  await expect(page.getByRole('heading', { name: '账号清理' })).toBeVisible()

  await page.goto('/admin/packages')
  await page.getByLabel('套餐代码').fill(code)
  await page.getByLabel('套餐名称').fill('E2E 管理套餐')
  await page.getByRole('button', { name: '创建套餐' }).click()
  await expect(page.getByText(code)).toBeVisible()
  const packages = await (await page.request.get('/api/admin/packages')).json()
  const created = packages.items.find((item: any) => item.code === code)
  expect(created).toBeTruthy()
  await page.request.delete(`/api/admin/packages/${created.id}`)
})
