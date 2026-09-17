import type { ReactNode, RefObject } from 'react'
import { Icon, StatusChip } from './ui'

export type WorkspaceStep = 'target' | 'materials' | 'resume' | 'delivery'
export type TaskStatus = 'complete' | 'current' | 'available' | 'blocked'

export type WorkspaceStepItem = {
  id: WorkspaceStep
  label: string
  description: string
  status: TaskStatus
}

const stepIcons = {
  target: 'target',
  materials: 'material',
  resume: 'layers',
  delivery: 'delivery',
} as const

function statusLabel(status: TaskStatus) {
  return ({ complete: '已完成', current: '进行中', available: '可进入', blocked: '待解锁' } as const)[status]
}

export function StudioWorkspace({
  steps,
  activeStep,
  onStepChange,
  preview,
  previewOpen,
  onPreviewOpen,
  onPreviewClose,
  context,
  children,
}: {
  steps: WorkspaceStepItem[]
  activeStep: WorkspaceStep
  onStepChange: (step: WorkspaceStep) => void
  preview: ReactNode
  previewOpen: boolean
  onPreviewOpen: () => void
  onPreviewClose: () => void
  /** Persistent job context that belongs beside the resume, not in the task controls. */
  context: ReactNode
  children: ReactNode
}) {
  const active = steps.find((item) => item.id === activeStep)
  return (
    <div className="studio-workspace mt-6">
      <aside className="studio-steps" aria-label="简历制作进度">
        <p className="eyebrow hidden px-2 lg:block">制作流程</p>
        <div className="studio-step-list">
          {steps.map((item, index) => {
            const selected = item.id === activeStep
            return (
              <button
                key={item.id}
                type="button"
                aria-current={selected ? 'step' : undefined}
                className={`studio-step ${selected ? 'studio-step-active' : ''}`}
                onClick={() => onStepChange(item.id)}
                disabled={item.status === 'blocked'}
              >
                <span className="studio-step-icon"><Icon name={stepIcons[item.id]} className="h-4 w-4" /></span>
                <span className="min-w-0 text-left">
                  <span className="block text-sm font-semibold"><span className="mr-1.5 text-[11px] text-ink-muted">0{index + 1}</span>{item.label}</span>
                  <span className="mt-0.5 hidden truncate text-[11px] text-ink-muted lg:block">{item.description}</span>
                </span>
                <span className={`studio-status-dot studio-status-${item.status}`} title={statusLabel(item.status)} />
              </button>
            )
          })}
        </div>
        <div className="mt-auto hidden px-2 pb-2 pt-8 lg:block">
          <p className="text-xs leading-5 text-ink-muted">所有草稿与生成状态都会自动从服务器恢复。</p>
        </div>
      </aside>

      <aside className="studio-context-column" aria-label="目标岗位与投递入口">
        {context}
      </aside>

      <section className="studio-task-column min-w-0">
        <div className="studio-preview-trigger mb-3 items-center justify-between gap-3">
          <div>
            <p className="eyebrow">当前任务</p>
            <p className="mt-1 text-sm font-semibold">{active?.label}</p>
          </div>
          <button type="button" className="btn-secondary" onClick={onPreviewOpen}>
            <Icon name="file" className="h-4 w-4" />预览简历
          </button>
        </div>
        {children}
      </section>

      <aside className="studio-preview-column" aria-label="简历实时预览">
        {!previewOpen && preview}
      </aside>

      {previewOpen && (
        <div className="studio-preview-drawer" role="dialog" aria-modal="true" aria-label="简历预览">
          <div className="flex items-center justify-between border-b border-line bg-white px-4 py-3">
            <div>
              <p className="eyebrow">实时预览</p>
              <p className="mt-0.5 text-sm font-semibold">A4 简历</p>
            </div>
            <button type="button" className="icon-button" onClick={onPreviewClose} aria-label="关闭预览">
              <Icon name="close" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto bg-[#eceeea] p-3 sm:p-5">{preview}</div>
        </div>
      )}
    </div>
  )
}

export function StudioPanel({
  eyebrow,
  title,
  description,
  status,
  actions,
  children,
}: {
  eyebrow: string
  title: string
  description?: string
  status?: ReactNode
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card min-w-0 p-0">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="eyebrow text-sage">{eyebrow}</p>
            {status}
          </div>
          <h2 className="mt-1.5 text-xl font-semibold tracking-tight sm:text-2xl">{title}</h2>
          {description && <p className="mt-1.5 max-w-2xl text-sm leading-6 text-ink-secondary">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className="px-5 py-5 sm:px-6">{children}</div>
    </section>
  )
}

export function A4Preview({
  containerRef,
  versionId,
  contentHash,
  scale,
  width,
  height,
  showHeader = true,
}: {
  containerRef: RefObject<HTMLDivElement>
  versionId: string
  contentHash: string
  scale: number
  width: number
  height: number
  showHeader?: boolean
}) {
  return (
    <div className="studio-preview-surface">
      {showHeader && <div className="mb-3 flex items-center justify-between px-1">
        <div>
          <p className="eyebrow">实时预览</p>
          <p className="mt-1 text-sm font-semibold">A4 · 单页</p>
        </div>
        <StatusChip tone="success"><span className="h-1.5 w-1.5 rounded-full bg-current" />已同步</StatusChip>
      </div>}
      <div ref={containerRef} className="w-full overflow-hidden rounded-xl border border-line bg-[#e8ebe6] p-2.5">
        <div className="relative mx-auto" style={{ width: `${width * scale}px`, height: `${height * scale}px` }}>
          <iframe
            title="A4 简历预览"
            data-testid="a4-preview"
            className="absolute left-0 top-0 bg-white shadow-lift"
            style={{ width: `${width}px`, height: `${height}px`, transform: `scale(${scale})`, transformOrigin: 'top left' }}
            src={`/api/resume-versions/${versionId}/studio-preview?v=${contentHash}`}
          />
        </div>
      </div>
    </div>
  )
}

export function PreviewPlaceholder({ profileReady, materialCount }: { profileReady: boolean; materialCount: number }) {
  return (
    <div className="studio-preview-surface">
      <p className="eyebrow">生成准备</p>
      <h2 className="mt-2 text-lg font-semibold">你的简历会显示在这里</h2>
      <p className="mt-2 text-sm leading-6 text-ink-secondary">完成岗位分析后即可生成双版本。素材不是前置条件，但会让内容更贴近你。</p>
      <div className="mt-5 space-y-2">
        <div className="flex items-center justify-between rounded-xl border border-line bg-white px-3.5 py-3 text-sm">
          <span>目标岗位</span><StatusChip tone={profileReady ? 'success' : 'neutral'}>{profileReady ? '已分析' : '未开始'}</StatusChip>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-line bg-white px-3.5 py-3 text-sm">
          <span>个人素材</span><StatusChip tone={materialCount ? 'success' : 'neutral'}>{materialCount ? `${materialCount} 条` : '可跳过'}</StatusChip>
        </div>
      </div>
      <div className="mt-6 space-y-2" aria-hidden="true">
        <div className="skeleton h-5 w-2/3" />
        <div className="skeleton h-3 w-full" />
        <div className="skeleton h-3 w-5/6" />
        <div className="skeleton mt-5 h-3 w-full" />
        <div className="skeleton h-3 w-4/5" />
      </div>
    </div>
  )
}
