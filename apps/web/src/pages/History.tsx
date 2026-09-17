import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Empty, ErrorState, Loading } from '../components/States'
import { Icon, PageHeader, StatusChip } from '../components/ui'

type SampleProject = {
  organization: string
  role_title: string
  section: string
  bullets: string[]
}

type Sample = {
  id: string
  direction: string
  direction_label: string
  title: string
  bullet_count: number
  projects: SampleProject[]
  writer_source?: string
  bundle_status?: string
  files: { json: string; html?: string; docx?: string }
}

type Group = { source: string; label: string; note: string; items: Sample[] }
type Index = { generated_at: string; groups: Group[] }

const DIRECTION_ORDER = ['mechanical', 'computer', 'ai', 'electronics', 'electrical']

async function loadIndex(): Promise<Index> {
  const response = await fetch('/generated-samples/index.json')
  if (!response.ok) throw new Error('无法加载生成记录')
  return (await response.json()) as Index
}

function SampleCard({ sample }: { sample: Sample }) {
  const [open, setOpen] = useState(false)
  const projects = sample.projects.filter((project) => project.bullets.length)
  return (
    <article className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip tone="info">{sample.direction_label}</StatusChip>
            {sample.writer_source && (
              <StatusChip tone={sample.writer_source === 'model' ? 'success' : 'warning'}>
                {sample.writer_source === 'model' ? '模型生成' : '本地回退'}
              </StatusChip>
            )}
            {sample.bundle_status && <StatusChip tone="neutral">{sample.bundle_status}</StatusChip>}
          </div>
          <h3 className="mt-2 text-base font-semibold tracking-tight">{sample.title || '未命名简历'}</h3>
          <p className="mt-1 text-xs text-ink-muted">
            {projects.length} 段经历 · {sample.bullet_count} 条要点
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => setOpen((value) => !value)}>
          <Icon name={open ? 'close' : 'file'} className="h-4 w-4" />
          {open ? '收起' : '查看内容'}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-3 border-t border-line pt-4">
          {projects.map((project, index) => (
            <div key={`${project.organization}-${index}`}>
              <p className="text-sm font-semibold">
                {project.organization || project.section}
                {project.role_title ? ` · ${project.role_title}` : ''}
              </p>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">
                {project.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-3">
        <a className="btn-secondary" href={sample.files.json} download>
          <Icon name="download" className="h-4 w-4" />下载 JSON
        </a>
        {sample.files.html && (
          <a className="btn-secondary" href={sample.files.html} target="_blank" rel="noreferrer">
            <Icon name="file" className="h-4 w-4" />打开 HTML
          </a>
        )}
        {sample.files.docx && (
          <a className="btn-secondary" href={sample.files.docx} download>
            <Icon name="download" className="h-4 w-4" />下载 DOCX
          </a>
        )}
      </div>
    </article>
  )
}

export function History() {
  const index = useQuery({ queryKey: ['generated-samples'], queryFn: loadIndex })
  const [direction, setDirection] = useState('all')

  const directions = useMemo(() => {
    const present = new Set<string>()
    for (const group of index.data?.groups || []) {
      for (const item of group.items) present.add(item.direction)
    }
    return [...DIRECTION_ORDER.filter((value) => present.has(value)), ...[...present].filter((value) => !DIRECTION_ORDER.includes(value))]
  }, [index.data])

  if (index.isLoading) return <Loading />
  if (index.error) return <ErrorState error={index.error} />

  const groups = (index.data?.groups || [])
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => direction === 'all' || item.direction === direction),
    }))
    .filter((group) => group.items.length)
  const total = (index.data?.groups || []).reduce((sum, group) => sum + group.items.length, 0)

  return (
    <>
      <PageHeader
        kicker="生成记录"
        title="历史生成记录"
        lead={`共 ${total} 份虚构简历样本，按来源与方向分类，可查看正文并下载。`}
      />
      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          className={direction === 'all' ? 'btn' : 'btn-secondary'}
          onClick={() => setDirection('all')}
        >
          全部方向
        </button>
        {directions.map((value) => {
          const label = (index.data?.groups || [])
            .flatMap((group) => group.items)
            .find((item) => item.direction === value)?.direction_label || value
          return (
            <button
              key={value}
              type="button"
              className={direction === value ? 'btn' : 'btn-secondary'}
              onClick={() => setDirection(value)}
            >
              {label}
            </button>
          )
        })}
      </div>

      {!groups.length && <div className="mt-6"><Empty title="没有符合条件的生成记录。" /></div>}

      {groups.map((group) => (
        <section key={group.source} className="mt-7">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-lg font-semibold tracking-tight">{group.label}</h2>
            <p className="text-xs text-ink-muted">{group.note}</p>
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {group.items.map((sample) => <SampleCard key={sample.id} sample={sample} />)}
          </div>
        </section>
      ))}
    </>
  )
}
