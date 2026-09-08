import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'
import { Alert, PageHeader } from '../components/ui'

const SIX_PART_LABELS: Record<string, string> = {
  context: '背景',
  goal: '目标',
  action: '行动',
  tools: '工具',
  result: '结果',
  learning: '收获',
}

type GuideCard = {
  bullet_id: string
  main_question?: string
  follow_ups?: string[]
  six_part_story?: Record<string, string>
  personal_boundary?: string
  verification?: string
  danger?: string
  exposure_questions?: string[]
  honest_boundary?: string
  missing_evidence?: string
  future_answer?: string
}

type Guide = {
  id: string
  kind: string
  status: string
  practice_enabled: boolean
  scoring_enabled: boolean
  voice_enabled: boolean
  degraded?: boolean
  degraded_reason?: string
  content_json: {
    cards?: GuideCard[]
    self_intro_60s?: string
    self_intro_90s?: string
    jd_questions?: string[]
    motivation?: string
    questions_to_ask?: string[]
    checklist?: string[]
    degraded?: boolean
    degraded_reason?: string
  }
}

function ListBlock({ title, items }: { title: string; items?: string[] }) {
  const rows = (items || []).map((item) => String(item).trim()).filter(Boolean)
  if (!rows.length) return null
  return (
    <article className="card">
      <h2 className="font-bold tracking-tight">{title}</h2>
      <ul className="mt-3 space-y-2 text-sm leading-6 text-black/75">
        {rows.map((item) => <li className="rounded-xl bg-black/[0.03] px-3 py-2" key={item}>{item}</li>)}
      </ul>
    </article>
  )
}

function TextBlock({ title, text }: { title: string; text?: string }) {
  if (!text) return null
  return (
    <article className="card">
      <h2 className="font-bold tracking-tight">{title}</h2>
      <p className="mt-3 whitespace-pre-wrap leading-7 text-black/75">{text}</p>
    </article>
  )
}

export function InterviewGuides() {
  const client = useQueryClient()
  const [params] = useSearchParams()
  const guideId = params.get('guide') || ''
  const guide = useQuery({
    queryKey: ['interview-guide', guideId],
    queryFn: () => api<Guide>(`/api/interview-guides/${guideId}`),
    enabled: Boolean(guideId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'generating' ? 2000 : false
    },
  })
  const regenerate = useMutation({
    mutationFn: () => api<Guide>(`/api/interview-guides/${guideId}/regenerate`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['interview-guide', guideId] }),
  })
  const cards = useMemo(() => guide.data?.content_json.cards || [], [guide.data])
  const content = guide.data?.content_json
  if (guide.isLoading) return <Loading />
  if (guide.error) return <ErrorState error={guide.error} />
  const degraded = Boolean(guide.data?.degraded || content?.degraded)
  const kindLabel = guide.data?.kind === 'target' ? '蓝图风险指南' : '求职版作战指南'
  return (
    <>
      <PageHeader
        kicker="准备材料"
        title="面试指南"
        lead="第一阶段只提供查看和导出，不要求作答、评分或预约顾问。"
      />
      {!guideId && <div className="mt-6"><Empty title="从工作台打开一份绑定简历版本的指南。" /></div>}
      {guide.data && (
        <div className="mt-6 space-y-4">
          <div className="card flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm">
              状态：{guide.data.status === 'stale' ? '已过期，请重新生成指南' : `${kindLabel} · ${guide.data.status}`}
            </p>
            <div className="flex flex-wrap gap-2">
              <a className="btn-secondary" href={`/api/interview-guides/${guide.data.id}/download`}>下载指南</a>
              {guide.data.status === 'stale' && (
                <button className="btn" onClick={() => regenerate.mutate()}>重新生成指南</button>
              )}
            </div>
          </div>
          {(guide.data.status === 'queued' || guide.data.status === 'generating') && (
            <Alert tone="info">
              <span className="mr-2 inline-flex align-middle"><span className="spinner text-sage" /></span>
              指南正在生成，完成后会自动刷新。
            </Alert>
          )}
          {degraded && (
            <Alert tone="warning" role="status">
              {guide.data.degraded_reason || content?.degraded_reason || '使用通用模板降级方案'}
            </Alert>
          )}
          <TextBlock title="60 秒自我介绍" text={content?.self_intro_60s} />
          <TextBlock title="90 秒自我介绍" text={content?.self_intro_90s} />
          <TextBlock title="岗位动机" text={content?.motivation} />
          <ListBlock title="JD 专业与行为题" items={content?.jd_questions} />
          <ListBlock title="向面试官的反问" items={content?.questions_to_ask} />
          <ListBlock title="面试前检查表" items={content?.checklist} />
          {cards.map((card) => (
            <article key={card.bullet_id} className="card space-y-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-black/40">要点 {card.bullet_id}</p>
              <h2 className="text-lg font-bold tracking-tight">{card.main_question || card.exposure_questions?.[0]}</h2>
              {!!card.follow_ups?.length && (
                <div>
                  <h3 className="text-sm font-semibold text-sage">连续追问</h3>
                  <ul className="mt-2 space-y-1.5 text-sm leading-6">
                    {card.follow_ups.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}
              {card.six_part_story && Object.values(card.six_part_story).some(Boolean) && (
                <div>
                  <h3 className="text-sm font-semibold text-sage">六段式讲法</h3>
                  <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                    {Object.entries(SIX_PART_LABELS).map(([key, label]) => (
                      card.six_part_story?.[key] ? (
                        <li key={key} className="rounded-xl bg-black/[0.03] px-3 py-2 text-sm">
                          <span className="font-medium">{label}：</span>{card.six_part_story[key]}
                        </li>
                      ) : null
                    ))}
                  </ul>
                </div>
              )}
              {card.personal_boundary && <p><span className="font-medium">个人贡献边界：</span>{card.personal_boundary}</p>}
              {card.verification && <p><span className="font-medium">核验材料：</span>{card.verification}</p>}
              {card.danger && <p><span className="font-medium">危险说法：</span>{card.danger}</p>}
              {!!card.exposure_questions?.length && (
                <div>
                  <h3 className="text-sm font-semibold text-sage">可能被问穿的问题</h3>
                  <ul className="mt-2 space-y-1.5 text-sm leading-6">
                    {card.exposure_questions.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}
              {card.honest_boundary && <p className="rounded-xl bg-amber-50 px-3 py-2 text-amber-800">{card.honest_boundary}</p>}
              {card.missing_evidence && <p><span className="font-medium">缺少的证据：</span>{card.missing_evidence}</p>}
              {card.future_answer && <p><span className="font-medium">补齐后的答法：</span>{card.future_answer}</p>}
            </article>
          ))}
        </div>
      )}
    </>
  )
}
