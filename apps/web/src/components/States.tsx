export function Loading({ text = '正在加载…' }: { text?: string }) {
  return (
    <div className="card" role="status">
      <div className="flex items-center gap-3 text-sm text-ink-secondary"><span className="spinner text-sage" />{text}</div>
      <div className="mt-5 space-y-2" aria-hidden="true"><div className="skeleton h-4 w-1/3" /><div className="skeleton h-3 w-full" /><div className="skeleton h-3 w-4/5" /></div>
    </div>
  )
}

export function Empty({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-ink/[0.012] px-5 py-8 text-center">
      <div className="mx-auto mb-3 grid h-9 w-9 place-items-center rounded-lg border border-line bg-white text-sage">
        <span className="text-lg leading-none">+</span>
      </div>
      <p className="text-ink-secondary">{title}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="alert alert-danger" role="alert">
      {error instanceof Error ? error.message : '加载失败，请重试。'}
    </div>
  )
}
