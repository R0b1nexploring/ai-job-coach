export type ApiError = { error: { code: string; message: string; details: Record<string, unknown>; request_id: string } }

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers, credentials: 'include' })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as ApiError | null
    throw new Error(body?.error?.message || '请求失败，请稍后重试。')
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

