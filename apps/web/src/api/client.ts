export type ApiError = { error: { code: string; message: string; details: Record<string, unknown>; request_id: string } }

export class ApiRequestError extends Error {
  code: string
  details: Record<string, unknown>
  requestId: string
  status: number

  constructor(payload: ApiError['error'], status: number) {
    super(payload.message)
    this.name = 'ApiRequestError'
    this.code = payload.code || 'HTTP_ERROR'
    this.details = payload.details || {}
    this.requestId = payload.request_id || ''
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers, credentials: 'include' })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as ApiError | null
    if (body?.error) throw new ApiRequestError(body.error, response.status)
    throw new ApiRequestError({
      code: 'HTTP_ERROR', message: '请求失败，请稍后重试。', details: {},
      request_id: response.headers.get('x-request-id') || '',
    }, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}
