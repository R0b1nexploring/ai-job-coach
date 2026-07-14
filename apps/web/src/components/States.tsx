export function Loading({ text = '正在加载…' }: { text?: string }) { return <div className="card animate-pulse text-black/60" role="status">{text}</div> }
export function Empty({ title, action }: { title: string; action?: React.ReactNode }) { return <div className="card text-center"><p className="text-black/60">{title}</p>{action}</div> }
export function ErrorState({ error }: { error: unknown }) { return <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700" role="alert">{error instanceof Error ? error.message : '加载失败，请重试。'}</div> }

