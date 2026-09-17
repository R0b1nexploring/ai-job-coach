import type { ReactNode } from 'react'

type IconName =
  | 'compass'
  | 'studio'
  | 'guides'
  | 'settings'
  | 'logout'
  | 'spark'
  | 'file'
  | 'check'
  | 'download'
  | 'alert'
  | 'target'
  | 'material'
  | 'layers'
  | 'delivery'
  | 'chevron-right'
  | 'menu'
  | 'close'
  | 'plus'
  | 'upload'
  | 'history'

export function Icon({ name, className = 'h-4 w-4' }: { name: IconName; className?: string }) {
  const common = {
    className,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
  switch (name) {
    case 'compass':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8.25" />
          <path fill="currentColor" stroke="none" d="M12 6.2 14.3 12 12 17.8 9.7 12Z" />
        </svg>
      )
    case 'studio':
      return (
        <svg {...common}>
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 17V5.5A1.5 1.5 0 0 1 8 4h9.5A1.5 1.5 0 0 1 19 5.5V17" />
          <path d="M9 8h6M9 11.5h4" />
        </svg>
      )
    case 'guides':
      return (
        <svg {...common}>
          <path d="M8 9h8M8 13h5" />
          <path d="M5 5h14a1 1 0 0 1 1 1v10.2a1 1 0 0 1-1 1H9.2L5 20.5V6a1 1 0 0 1 1-1Z" />
        </svg>
      )
    case 'settings':
      return (
        <svg {...common}>
          <path d="M4 8h8M16 8h4M4 16h4M12 16h8" />
          <circle cx="14" cy="8" r="2.2" />
          <circle cx="8" cy="16" r="2.2" />
        </svg>
      )
    case 'logout':
      return (
        <svg {...common}>
          <path d="M10 7V5.5A1.5 1.5 0 0 1 11.5 4h7A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 10 18.5V17" />
          <path d="M4 12h10M7.5 8.5 4 12l3.5 3.5" />
        </svg>
      )
    case 'spark':
      return (
        <svg {...common}>
          <path d="M12 3.5 13.7 9l5.3 1.3L13.7 11.6 12 17l-1.7-5.4L5 10.3 10.3 9Z" />
        </svg>
      )
    case 'file':
      return (
        <svg {...common}>
          <path d="M14 3.5H8A1.5 1.5 0 0 0 6.5 5v14A1.5 1.5 0 0 0 8 20.5h8A1.5 1.5 0 0 0 17.5 19V8Z" />
          <path d="M14 3.5V8h4.5" />
        </svg>
      )
    case 'check':
      return (
        <svg {...common}>
          <path d="M20 6.5 9.5 17 4 11.5" />
        </svg>
      )
    case 'download':
      return (
        <svg {...common}>
          <path d="M12 4v11M8 11.5 12 15.5 16 11.5" />
          <path d="M5 19.5h14" />
        </svg>
      )
    case 'alert':
      return (
        <svg {...common}>
          <path d="M12 9v4.5M12 16.8h.01" />
          <path d="M10.2 4.8 2.9 17.2A2 2 0 0 0 4.7 20h14.6a2 2 0 0 0 1.8-2.8L13.8 4.8a2 2 0 0 0-3.6 0Z" />
        </svg>
      )
    case 'target':
      return <svg {...common}><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
    case 'material':
      return <svg {...common}><path d="M7 3.5h10A1.5 1.5 0 0 1 18.5 5v14A1.5 1.5 0 0 1 17 20.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5Z" /><path d="M9 8h6M9 12h6M9 16h4" /></svg>
    case 'layers':
      return <svg {...common}><path d="m12 3 8 4.5-8 4.5-8-4.5Z" /><path d="m4 12 8 4.5 8-4.5M4 16.5 12 21l8-4.5" /></svg>
    case 'delivery':
      return <svg {...common}><path d="M4 5.5h16v13H4Z" /><path d="M8 9h8M8 13h5" /><path d="m16 16 2 2 3-3" /></svg>
    case 'chevron-right':
      return <svg {...common}><path d="m9 5 7 7-7 7" /></svg>
    case 'menu':
      return <svg {...common}><path d="M4 7h16M4 12h16M4 17h16" /></svg>
    case 'close':
      return <svg {...common}><path d="m6 6 12 12M18 6 6 18" /></svg>
    case 'plus':
      return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>
    case 'upload':
      return <svg {...common}><path d="M12 16V4M7.5 8.5 12 4l4.5 4.5" /><path d="M5 13v6.5h14V13" /></svg>
    case 'history':
      return <svg {...common}><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" /><path d="M3.5 4v4h4" /><path d="M12 8v4.3l3 1.8" /></svg>
  }
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5 text-inherit">
      <span className="grid h-8 w-8 place-items-center rounded bg-ink text-canvas">
        <Icon name="compass" className="h-5 w-5" />
      </span>
      {!compact && <span className="text-[17px] font-semibold tracking-tight">求职罗盘</span>}
    </span>
  )
}

export function PageHeader({
  kicker,
  title,
  lead,
  extra,
}: {
  kicker?: string
  title: ReactNode
  lead?: ReactNode
  extra?: ReactNode
}) {
  return (
    <header className="page-header">
      {kicker && <p className="badge">{kicker}</p>}
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <h1 className="page-title">{title}</h1>
          {lead && <p className="page-lead">{lead}</p>}
        </div>
        {extra}
      </div>
    </header>
  )
}

export function Alert({
  tone = 'info',
  children,
  role,
}: {
  tone?: 'info' | 'success' | 'warning' | 'danger'
  children: ReactNode
  role?: 'status' | 'alert'
}) {
  return (
    <p className={`alert alert-${tone}`} role={role}>
      {children}
    </p>
  )
}

export function StepIndex({ n }: { n: string }) {
  return <span className="step-index">{n}</span>
}

export function StatusChip({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
  children: ReactNode
}) {
  const tones = {
    neutral: 'border-line bg-ink/[0.03] text-ink-secondary',
    success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    warning: 'border-amber-200 bg-amber-50 text-amber-800',
    danger: 'border-red-200 bg-red-50 text-red-700',
    info: 'border-sky-200 bg-sky-50 text-sky-700',
  }
  return <span className={`status-chip ${tones[tone]}`}>{children}</span>
}
