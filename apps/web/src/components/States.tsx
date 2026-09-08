export function Loading({ text = '正在加载…' }: { text?: string }) {
  return (
    <div className="card flex items-center gap-3 text-black/60" role="status">
      <span className="spinner text-sage" />
      {text}
    </div>
  )
}

export function Empty({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="card text-center">
      <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-sage/10 text-sage">
        <span className="text-lg">·</span>
      </div>
      <p className="text-black/60">{title}</p>
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
