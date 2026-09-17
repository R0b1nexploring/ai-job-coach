import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'
import type { ListResponse, Resume } from '../types'

const channelTypeLabels: Record<string, string> = {
  career_page: '公司招聘页',
  email: '投递邮箱',
  form: '投递表单',
}
const scopeLabels: Record<string, string> = { campus: '校招', experienced: '社招', both: '校招与社招' }
const verifyLabels: Record<string, string> = { unverified: '待核验', reachable: '可访问', dead: '已失效' }

export function Channels() {
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [channelType, setChannelType] = useState('')
  const [resumeId, setResumeId] = useState('')
  const [message, setMessage] = useState('')
  const channels = useQuery({
    queryKey: ['channels', search, channelType],
    queryFn: () => api<any>(`/api/channels?search=${encodeURIComponent(search)}&channel_type=${channelType}`),
  })
  const resumes = useQuery({
    queryKey: ['resumes'],
    queryFn: () => api<ListResponse<Resume>>('/api/resumes'),
  })
  const reportDead = useMutation({
    mutationFn: (id: string) => api<any>(`/api/channels/${id}/report-dead`, { method: 'POST' }),
    onSuccess: (data) => {
      setMessage(data.verify_status === 'dead' ? '该渠道已累计 3 次失效反馈，并已退出岗位读取允许列表。' : `已记录失效反馈（${data.dead_reports}/3）。`)
      client.invalidateQueries({ queryKey: ['channels'] })
    },
  })
  const discover = useMutation({
    mutationFn: (id: string) => api<any>(`/api/channels/${id}/discover-jobs`, {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, limit: 10 }),
    }),
    onSuccess: (data) => {
      setMessage(data.fallback_used ? `渠道读取失败，已安全回退：${data.source_error}` : `已从公司招聘页读取并保存 ${data.total} 个岗位。`)
      client.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  const copyEmail = async (email: string) => {
    await navigator.clipboard.writeText(email)
    setMessage('投递邮箱已复制。')
  }

  if (channels.isLoading || resumes.isLoading) return <Loading />
  if (channels.error || resumes.error) return <ErrorState error={channels.error || resumes.error} />

  return (
    <>
      <span className="badge">公司级入口 · 不是岗位源</span>
      <h1 className="page-title mt-3">投递渠道</h1>
      <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        系统只提供运营者自行确认许可后的导入能力，不随产品分发第三方渠道数据；不会自动投递或发送邮件。
      </p>
      <section className="card mt-5 grid gap-3 md:grid-cols-3">
        <label>
          <span className="label">搜索公司</span>
          <input aria-label="搜索渠道公司" className="field" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="输入公司名称" />
        </label>
        <label>
          <span className="label">渠道类型</span>
          <select aria-label="渠道类型" className="field" value={channelType} onChange={(event) => setChannelType(event.target.value)}>
            <option value="">全部</option>
            <option value="career_page">公司招聘页</option>
            <option value="email">投递邮箱</option>
            <option value="form">投递表单</option>
          </select>
        </label>
        <label>
          <span className="label">读取岗位时使用的简历</span>
          <select aria-label="渠道岗位简历" className="field" value={resumeId} onChange={(event) => setResumeId(event.target.value)}>
            <option value="">请选择</option>
            {resumes.data?.items.map((resume) => <option value={resume.id} key={resume.id}>{resume.display_name}</option>)}
          </select>
        </label>
      </section>
      {message && <p className="mt-4 rounded-xl bg-green-50 p-3 text-green-700">{message}</p>}
      {(reportDead.error || discover.error) && <div className="mt-4"><ErrorState error={reportDead.error || discover.error} /></div>}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {channels.data?.items?.length ? channels.data.items.map((channel: any) => (
          <article className="card" key={channel.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">{channel.company_name}</h2>
                <p className="mt-1 text-sm text-ink-secondary">{channelTypeLabels[channel.channel_type]} · {scopeLabels[channel.scope]}</p>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${channel.verify_status === 'dead' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
                {verifyLabels[channel.verify_status]}
              </span>
            </div>
            <p className="mt-3 text-xs text-ink-muted">来源更新时间：{channel.source_updated_at ? new Date(channel.source_updated_at).toLocaleDateString('zh-CN') : '未知'}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {channel.url && <a className="btn-secondary" href={channel.url} target="_blank" rel="noreferrer">打开投递入口</a>}
              {channel.email && <button className="btn-secondary" onClick={() => copyEmail(channel.email)}>复制邮箱</button>}
              {channel.channel_type === 'career_page' && channel.verify_status !== 'dead' && (
                <button className="btn" disabled={!resumeId || discover.isPending} onClick={() => discover.mutate(channel.id)}>读取公开岗位</button>
              )}
              {channel.verify_status !== 'dead' && <button className="text-sm text-red-700" onClick={() => reportDead.mutate(channel.id)}>报告失效</button>}
            </div>
          </article>
        )) : <Empty title="暂无可用渠道。请由运营者通过本地导入脚本添加已获许可的数据。" />}
      </div>
    </>
  )
}
