import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import App from '../app/App'
import { AuthProvider } from '../app/AuthContext'
import { onboardingDraftKey } from '../utils/onboardingDraft'

const currentUser = {
  id: 'user-b', email: 'user-b@example.test', display_name: '用户 B', role: 'user', status: 'active',
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider><App /></AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function authenticatedFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.includes('/api/auth/logout') && init?.method === 'POST') {
      return new Response(null, { status: 204 })
    }
    if (path.includes('/api/auth/me')) return jsonResponse(currentUser)
    if (path.includes('/api/notifications')) return jsonResponse({ items: [], unread_count: 0 })
    return jsonResponse({})
  })
}

test('损坏的当前用户草稿会被清除且引导页仍可打开', async () => {
  const key = onboardingDraftKey(currentUser.id)
  localStorage.setItem(key, '{bad json')
  vi.stubGlobal('fetch', authenticatedFetch())

  renderApp('/app/onboarding')

  expect(await screen.findByText('建立求职档案')).toBeInTheDocument()
  expect(screen.getByLabelText('学校')).toHaveValue('')
  expect(localStorage.getItem(key)).toBeNull()
})

test('字段类型损坏的草稿也会回退默认值', async () => {
  const key = onboardingDraftKey(currentUser.id)
  localStorage.setItem(key, JSON.stringify({ school: ['不合法'], target_cities: {} }))
  vi.stubGlobal('fetch', authenticatedFetch())

  renderApp('/app/onboarding')

  expect(await screen.findByLabelText('学校')).toHaveValue('')
  expect(localStorage.getItem(key)).toBeNull()
})

test('引导草稿按用户隔离保存', async () => {
  const otherKey = onboardingDraftKey('user-a')
  const currentKey = onboardingDraftKey(currentUser.id)
  localStorage.setItem(otherKey, JSON.stringify({ school: '用户 A 的学校' }))
  vi.stubGlobal('fetch', authenticatedFetch())
  const user = userEvent.setup()

  renderApp('/app/onboarding')

  const school = await screen.findByLabelText('学校')
  expect(school).toHaveValue('')
  await user.type(school, '用户 B 的学校')
  await waitFor(() => {
    expect(JSON.parse(localStorage.getItem(currentKey) || '{}').school).toBe('用户 B 的学校')
  })
  expect(JSON.parse(localStorage.getItem(otherKey) || '{}').school).toBe('用户 A 的学校')
})

test('退出登录会清除当前用户的引导草稿', async () => {
  const key = onboardingDraftKey(currentUser.id)
  localStorage.setItem(key, JSON.stringify({ school: '退出前草稿' }))
  vi.stubGlobal('fetch', authenticatedFetch())
  const user = userEvent.setup()

  renderApp('/app/dashboard')

  await user.click(await screen.findByRole('button', { name: '退出登录' }))
  await waitFor(() => expect(localStorage.getItem(key)).toBeNull())
})

test.each([
  ['服务端 500', () => Promise.resolve(jsonResponse({ error: {
    code: 'INTERNAL_ERROR', message: '内部错误', details: {}, request_id: 'request-1',
  } }, 500))],
  ['网络错误', () => Promise.reject(new TypeError('network unavailable'))],
])('%s 不会被误判为未登录', async (_label, fetchResult) => {
  vi.stubGlobal('fetch', vi.fn(fetchResult))

  renderApp('/app/dashboard')

  expect(await screen.findByText('暂时无法验证登录状态')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '欢迎回来' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '重新验证' })).toBeInTheDocument()
})
