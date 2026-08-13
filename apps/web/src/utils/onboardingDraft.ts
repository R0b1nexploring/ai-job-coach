const DRAFT_PREFIX = 'ai-job-coach-onboarding-draft'
const LEGACY_DRAFT_KEY = DRAFT_PREFIX

export function onboardingDraftKey(userId: string): string {
  return `${DRAFT_PREFIX}:${userId}`
}

function browserStorage(): Storage | undefined {
  if (typeof window === 'undefined') return undefined
  try { return window.localStorage } catch { return undefined }
}

function removeSafely(storage: Storage, key: string): void {
  try { storage.removeItem(key) } catch { /* Storage may be disabled by the browser. */ }
}

export function loadOnboardingDraft<T extends object>(
  userId: string,
  isValid?: (value: Record<string, unknown>) => boolean,
): Partial<T> | undefined {
  const storage = browserStorage()
  if (!storage) return undefined
  removeSafely(storage, LEGACY_DRAFT_KEY)
  const key = onboardingDraftKey(userId)
  try {
    const raw = storage.getItem(key)
    if (!raw) return undefined
    const value: unknown = JSON.parse(raw)
    if (value === null || Array.isArray(value) || typeof value !== 'object') {
      removeSafely(storage, key)
      return undefined
    }
    const draft = value as Record<string, unknown>
    if (isValid && !isValid(draft)) {
      removeSafely(storage, key)
      return undefined
    }
    return draft as Partial<T>
  } catch {
    removeSafely(storage, key)
    return undefined
  }
}

export function saveOnboardingDraft(userId: string, value: unknown): void {
  const storage = browserStorage()
  if (!storage) return
  try { storage.setItem(onboardingDraftKey(userId), JSON.stringify(value)) } catch {
    // Draft persistence is best effort; form entry must continue if storage is full/blocked.
  }
}

export function clearOnboardingDraft(userId?: string): void {
  const storage = browserStorage()
  if (!storage) return
  removeSafely(storage, LEGACY_DRAFT_KEY)
  if (userId) removeSafely(storage, onboardingDraftKey(userId))
}
