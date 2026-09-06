import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'
import type { ExperienceEntry, ListResponse } from '../types'

const emptyForm = {
  kind: 'internship' as 'internship' | 'project',
  title: '',
  organization: '',
  role_title: '',
  location: '',
  start_date: '',
  end_date: '',
  summary: '',
  bullets: '',
  skills: '',
}

export function Experience() {
  const client = useQueryClient()
  const [tab, setTab] = useState<'own' | 'template'>('own')
  const [form, setForm] = useState(emptyForm)
  const [message, setMessage] = useState('')
  const entries = useQuery({
    queryKey: ['experience'],
    queryFn: () => api<ListResponse<ExperienceEntry>>('/api/experience'),
  })
  const create = useMutation({
    mutationFn: () => api<ExperienceEntry>('/api/experience', {
      method: 'POST',
      body: JSON.stringify({
        kind: form.kind,
        title: form.title,
        organization: form.organization,
        role_title: form.role_title,
        location: form.location,
        start_date: form.start_date,
        end_date: form.end_date,
        summary: form.summary,
        bullets_json: splitLines(form.bullets),
        skills_json: splitLines(form.skills),
      }),
    }),
    onSuccess: () => {
      setMessage('已保存草稿素材，确认后才会写入事实库。')
      setForm(emptyForm)
      client.invalidateQueries({ queryKey: ['experience'] })
    },
  })
  const copyTemplate = useMutation({
    mutationFn: (id: string) => api<ExperienceEntry>(`/api/experience/from-template/${id}`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('已按范本创建草稿。请改成你自己的真实组织与内容后再确认。')
      setTab('own')
      client.invalidateQueries({ queryKey: ['experience'] })
    },
  })
  const confirm = useMutation({
    mutationFn: (id: string) => api<ExperienceEntry>(`/api/experience/${id}/confirm`, { method: 'POST' }),
    onSuccess: () => {
      setMessage('已确认并加入事实库。')
      client.invalidateQueries({ queryKey: ['experience'] })
    },
  })
  const own = useMemo(
    () => (entries.data?.items || []).filter((item) => item.is_own),
    [entries.data?.items],
  )
  const templates = useMemo(
    () => (entries.data?.items || []).filter((item) => item.is_template),
    [entries.data?.items],
  )
  const internships = own.filter((item) => item.kind === 'internship')
  const projects = own.filter((item) => item.kind === 'project')

  if (entries.isLoading) return <Loading />
  if (entries.error) return <ErrorState error={entries.error} />

  return (
    <>
      <span className="badge">实习 · 项目 · 范本</span>
      <h1 className="mt-3 text-4xl font-black">经历库</h1>
      <p className="mt-2 max-w-2xl text-sm text-black/60">
        实习和项目是生成简历的材料库。可以不先上传文件，直接记下真实经历。全站范本只供对照，不能当成你已经做过的事。
      </p>
      {message && <p className="mt-5 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
      {(create.error || copyTemplate.error || confirm.error) && (
        <div className="mt-5">
          <ErrorState error={create.error || copyTemplate.error || confirm.error} />
        </div>
      )}
      <div className="mt-6 flex gap-2">
        <button className={tab === 'own' ? 'btn' : 'btn-secondary'} onClick={() => setTab('own')}>我的经历</button>
        <button className={tab === 'template' ? 'btn' : 'btn-secondary'} onClick={() => setTab('template')}>全站范本</button>
      </div>
      {tab === 'own' ? (
        <>
          <form
            className="card mt-6 grid gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              create.mutate()
            }}
          >
            <h2 className="text-xl font-bold">添加真实经历</h2>
            <div className="flex gap-2">
              <label className="text-sm"><input className="mr-2" type="radio" checked={form.kind === 'internship'} onChange={() => setForm((current) => ({ ...current, kind: 'internship' }))} />实习</label>
              <label className="text-sm"><input className="mr-2" type="radio" checked={form.kind === 'project'} onChange={() => setForm((current) => ({ ...current, kind: 'project' }))} />项目</label>
            </div>
            <input className="field" placeholder="标题，例如设备点检实习" value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} required />
            <div className="grid gap-3 sm:grid-cols-2">
              <input className="field" placeholder="组织 / 学校 / 自主项目" value={form.organization} onChange={(event) => setForm((current) => ({ ...current, organization: event.target.value }))} />
              <input className="field" placeholder="角色" value={form.role_title} onChange={(event) => setForm((current) => ({ ...current, role_title: event.target.value }))} />
              <input className="field" placeholder="地点" value={form.location} onChange={(event) => setForm((current) => ({ ...current, location: event.target.value }))} />
              <div className="grid grid-cols-2 gap-3">
                <input className="field" placeholder="开始 YYYY-MM" value={form.start_date} onChange={(event) => setForm((current) => ({ ...current, start_date: event.target.value }))} />
                <input className="field" placeholder="结束 YYYY-MM" value={form.end_date} onChange={(event) => setForm((current) => ({ ...current, end_date: event.target.value }))} />
              </div>
            </div>
            <textarea className="field min-h-24" placeholder="这段经历你实际做了什么，不要写没做过的数字或工具。" value={form.summary} onChange={(event) => setForm((current) => ({ ...current, summary: event.target.value }))} />
            <textarea className="field min-h-20" placeholder="要点，一行一条" value={form.bullets} onChange={(event) => setForm((current) => ({ ...current, bullets: event.target.value }))} />
            <input className="field" placeholder="技能，用逗号或换行分隔" value={form.skills} onChange={(event) => setForm((current) => ({ ...current, skills: event.target.value }))} />
            <button className="btn" disabled={!form.title.trim() || create.isPending}>保存到经历库</button>
          </form>
          <section className="mt-8">
            <h2 className="text-2xl font-bold">实习</h2>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              {internships.length ? internships.map((item) => <ExperienceCard key={item.id} item={item} onConfirm={() => confirm.mutate(item.id)} />) : <Empty title="还没有实习经历。" />}
            </div>
          </section>
          <section className="mt-8">
            <h2 className="text-2xl font-bold">项目</h2>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              {projects.length ? projects.map((item) => <ExperienceCard key={item.id} item={item} onConfirm={() => confirm.mutate(item.id)} />) : <Empty title="还没有项目经历。" />}
            </div>
          </section>
        </>
      ) : (
        <section className="mt-6 grid gap-4 lg:grid-cols-2">
          {templates.length ? templates.map((item) => (
            <article className="card" key={item.id}>
              <p className="badge">{item.kind === 'internship' ? '实习范本' : '项目范本'}</p>
              <h2 className="mt-3 font-bold">{item.title}</h2>
              <p className="mt-1 text-sm text-black/50">{item.organization} · {item.role_title}</p>
              <p className="mt-3 text-sm leading-6 text-black/70">{item.summary}</p>
              <ul className="mt-3 space-y-1 text-sm text-black/60">
                {item.bullets_json.map((bullet) => <li key={bullet}>• {bullet}</li>)}
              </ul>
              <button className="btn-secondary mt-4" onClick={() => copyTemplate.mutate(item.id)}>按此范本创建我的经历</button>
            </article>
          )) : <Empty title="暂无范本。" />}
        </section>
      )}
    </>
  )
}

function ExperienceCard({ item, onConfirm }: { item: ExperienceEntry; onConfirm: () => void }) {
  return (
    <article className="card">
      <div className="flex justify-between gap-3">
        <div>
          <h3 className="font-bold">{item.title}</h3>
          <p className="mt-1 text-sm text-black/50">{item.organization || '组织待填写'} · {item.role_title || '角色待填写'}</p>
          <p className="mt-1 text-xs text-black/45">{item.start_date || '开始时间未知'} – {item.end_date || '结束时间未知'}</p>
        </div>
        <span className="rounded-full bg-cream px-2.5 py-1 text-xs">{item.linked_to_facts ? '已入事实库' : '草稿'}</span>
      </div>
      <p className="mt-3 text-sm leading-6 text-black/70">{item.summary || '还没有经历说明。'}</p>
      {!item.linked_to_facts && (
        <button className="btn mt-4" onClick={onConfirm}>确认加入事实库</button>
      )}
    </article>
  )
}

function splitLines(value: string) {
  return value.split(/[\n,，；;]+/).map((item) => item.trim()).filter(Boolean)
}
