import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../app/AuthContext'
import { PublicHeader } from '../components/Layout'
import type { CoachResult } from '../types'

const MAX_FILE_BYTES = 10 * 1024 * 1024
const ALLOWED_RESUME_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]

function validateResume(file: File): string {
  if (!ALLOWED_RESUME_TYPES.includes(file.type)) return '仅支持 DOCX 或文本型 PDF 文件'
  if (file.size > MAX_FILE_BYTES) return '文件不能超过 10 MB'
  return ''
}

function validateImage(file: File): string {
  const allowed = ['image/png', 'image/jpeg', 'image/webp']
  if (!allowed.includes(file.type)) return '仅支持 PNG、JPG 或 WebP 图片'
  if (file.size > MAX_FILE_BYTES) return '文件不能超过 10 MB'
  return ''
}

export function Home() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  const resultRef = useRef<HTMLDivElement>(null)
  const [resume, setResume] = useState<File>()
  const [jdImage, setJdImage] = useState<File>()
  const [jdText, setJdText] = useState('')
  const [result, setResult] = useState<CoachResult>()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!user) { navigate('/login'); return }
    if (!resume || !jdImage) return
    const resumeErr = validateResume(resume)
    if (resumeErr) { setError(resumeErr); return }
    const imageErr = validateImage(jdImage)
    if (imageErr) { setError(imageErr); return }
    setError('')
    setSubmitting(true)
    const body = new FormData()
    body.append('resume_file', resume)
    body.append('jd_image', jdImage)
    if (jdText.trim()) body.append('jd_text', jdText.trim())
    try {
      const value = await api<CoachResult>('/api/coach/optimize', { method: 'POST', body })
      setResult(value)
      window.setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生成失败，请稍后重试。')
    } finally {
      setSubmitting(false)
    }
  }

  const restart = () => {
    setResult(undefined)
    setResume(undefined)
    setJdImage(undefined)
    setJdText('')
    setError('')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const ready = Boolean(resume && jdImage)
  return <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_#e3eee7,_transparent_38%),linear-gradient(#f8f5ee,#f5f1e8)]">
    <PublicHeader />
    <main>
      <section className="mx-auto max-w-5xl px-5 pb-12 pt-10 text-center md:pt-16">
        <p className="text-sm font-semibold tracking-[.18em] text-sage">只做一件事，把简历改得更贴合岗位</p>
        <h1 className="mx-auto mt-5 max-w-4xl text-4xl font-black leading-[1.12] tracking-tight md:text-6xl">上传简历和 JD 截图<br /><span className="text-sage">直接得到定制简历与面试引导</span></h1>
        <p className="mx-auto mt-6 max-w-2xl text-base leading-7 text-black/60">内容只基于你上传的原简历，不补造经历、工具和数字。生成结果是建议稿，请在使用前逐项核对。</p>
      </section>

      <form className="mx-auto max-w-4xl px-5 pb-20" onSubmit={submit}>
        <div className="grid gap-4 md:grid-cols-2">
          <UploadField
            accept=".docx,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf"
            description="支持 DOCX 或文本型 PDF，最大 10 MB"
            file={resume}
            label="上传你的简历"
            number="01"
            onChange={setResume}
          />
          <UploadField
            accept="image/png,image/jpeg,image/webp"
            description="支持 PNG、JPG 或 WebP，尽量截取完整 JD"
            file={jdImage}
            label="上传岗位 JD 截图"
            number="02"
            onChange={setJdImage}
          />
        </div>
        <label className="mt-4 block rounded-2xl border border-black/10 bg-white/70 p-5">
          <span className="label">JD 文字补充（可选）</span>
          <textarea aria-label="JD 文字补充" className="field min-h-24 resize-y" maxLength={20000} value={jdText} onChange={(event) => setJdText(event.target.value)} placeholder="如果截图较长或文字较小，可在这里补充粘贴；系统不会凭空补全识别不到的内容。" />
        </label>
        {error && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">{error}</p>}
        {!loading && !user && <p className="mt-5 text-center text-sm text-black/55">你可以先准备文件，提交时会进入登录页面。</p>}
        <div className="mt-6 text-center"><button className="btn min-w-64 px-8 py-3.5 text-base" disabled={!ready || submitting || loading}>
          {submitting ? '正在读取并生成，请稍候…' : user ? '生成简历与面试建议' : '登录后生成'}
        </button></div>
      </form>

      {result && <div ref={resultRef}><CoachResults result={result} onRestart={restart} /></div>}
    </main>
  </div>
}

function UploadField({ accept, description, file, label, number, onChange }: {
  accept: string
  description: string
  file?: File
  label: string
  number: string
  onChange: (file?: File) => void
}) {
  return <label className="group flex min-h-52 cursor-pointer flex-col justify-between rounded-2xl border border-dashed border-sage/45 bg-white p-6 text-left transition hover:-translate-y-0.5 hover:border-sage hover:shadow-lg">
    <input className="sr-only" type="file" accept={accept} onChange={(event) => onChange(event.target.files?.[0])} />
    <span className="text-sm font-bold text-coral">{number}</span>
    <span>
      <span className="block text-xl font-bold">{file ? file.name : label}</span>
      <span className="mt-2 block text-sm leading-6 text-black/50">{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · 点击可重新选择` : description}</span>
    </span>
  </label>
}

function ScoreRing({ score }: { score: number }) {
  const radius = 42
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference
  const color = score >= 80 ? '#4a9d6e' : score >= 60 ? '#c8a84e' : '#d46a5a'
  return <div className="relative inline-flex items-center justify-center">
    <svg width="100" height="100" className="-rotate-90">
      <circle cx="50" cy="50" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="8" />
      <circle cx="50" cy="50" r={radius} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} style={{ transition: 'stroke-dashoffset 0.6s ease' }} />
    </svg>
    <span className="absolute text-2xl font-black" style={{ color }}>{score}</span>
  </div>
}

function CoachResults({ result, onRestart }: { result: CoachResult; onRestart: () => void }) {
  const guide = result.interview_guide
  const content = result.tailored_resume.content
  return <section className="border-t border-black/10 bg-white/70 py-20">
    <div className="mx-auto max-w-4xl space-y-14 px-5">
      <div>
        <p className="text-sm font-bold tracking-[.16em] text-coral">岗位理解</p>
        <h2 className="mt-3 text-3xl font-black">{result.job.company_name} · {result.job.title}</h2>
        <p className="mt-2 text-black/50">{result.job.city || '地点未从截图中确认'} · OCR：{result.ocr_provider === 'rapidocr' ? '本地图片识别' : '使用文字补充'}</p>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <SummaryList title="主要职责" items={result.job.responsibilities} empty="截图中未识别出明确职责" />
          <SummaryList title="岗位要求" items={result.job.must_have} empty="截图中未识别出明确要求" />
          <SummaryList title="加分项" items={result.job.nice_to_have} empty="截图中未识别出明确加分项" />
          <SummaryList title="工作条件" items={result.job.work_conditions} empty="截图中未识别出明确工作条件" />
        </div>
        {result.job.keywords.length > 0 && <div className="mt-4 rounded-2xl border border-black/10 bg-white p-5">
          <h3 className="font-bold">岗位关键词</h3>
          <div className="mt-3 flex flex-wrap gap-2">{result.job.keywords.map((keyword, i) => <span className="badge" key={`kw-${i}`}>{keyword}</span>)}</div>
        </div>}
        {result.job.uncertain_fields.length > 0 && <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
          <h3 className="font-bold">需要你核对的信息</h3>
          <ul className="mt-3 space-y-2">{result.job.uncertain_fields.map((field, i) => <li key={`uf-${i}`}>• {field}</li>)}</ul>
          <p className="mt-3 text-xs leading-5 text-amber-800">这些内容来自图片识别或规则提取，尚未经过人工验证。</p>
        </div>}
      </div>

      {content.quality_score > 0 && <div>
        <p className="text-sm font-bold tracking-[.16em] text-coral">简历质量评分</p>
        <h2 className="mt-3 text-3xl font-black">基于当前简历规则评估</h2>
        <div className="mt-6 flex flex-col items-center gap-8 rounded-2xl border border-black/10 bg-white p-8 md:flex-row md:items-start">
          <ScoreRing score={content.quality_score} />
          <div className="flex-1 space-y-4">
            {content.quality_dimensions.map((dim, i) => <div key={`dim-${i}`} className="flex items-center gap-3">
              <span className="w-24 text-sm font-bold text-black/70">{dim.name}</span>
              <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-black/10">
                <div className="h-full rounded-full bg-sage transition-all duration-500" style={{ width: `${dim.score}%` }} />
              </div>
              <span className="w-10 text-right text-sm font-bold">{dim.score}</span>
            </div>)}
          </div>
        </div>
        {content.quality_suggestions.length > 0 && <div className="mt-4 rounded-2xl border border-sage/20 bg-sage/5 p-5">
          <h3 className="font-bold">改进建议</h3>
          <ul className="mt-3 space-y-2 text-sm leading-6">{content.quality_suggestions.map((s, i) => <li key={`qs-${i}`}>• {s}</li>)}</ul>
        </div>}
      </div>}

      <div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div><p className="text-sm font-bold tracking-[.16em] text-coral">定制简历</p><h2 className="mt-3 text-3xl font-black">建议稿，请逐项核对</h2></div>
          <div className="flex gap-3">
            <a className="btn-secondary" href={`/api/coach/resume-versions/${result.tailored_resume.id}/download`}>下载 DOCX</a>
            <button className="btn-secondary" onClick={onRestart}>重新开始</button>
          </div>
        </div>
        <article className="mt-6 rounded-2xl border border-black/10 bg-white p-6 shadow-sm md:p-9">
          <h3 className="border-b-2 border-sage pb-4 text-2xl font-black">{content.headline}</h3>
          <div className="mt-6 space-y-7">{content.sections.map((section, si) => <div key={`sec-${si}`}><h4 className="font-bold text-sage">{section.name}</h4><ul className="mt-3 space-y-3 text-sm leading-7">{section.items.map((item, ii) => <li key={`item-${si}-${ii}`}><div className="flex gap-3"><span className="text-sage">•</span><span>{item.text}</span></div>{item.improvement_suggestions?.length > 0 && <div className="mt-1 ml-6 space-y-1">{item.improvement_suggestions.map((s, si2) => <p key={`sug-${si}-${ii}-${si2}`} className="text-xs text-sage">💡 {s}</p>)}</div>}</li>)}</ul></div>)}</div>
          {content.excluded_gaps.length > 0 && <div className="mt-8 rounded-xl bg-amber-50 p-4 text-sm text-amber-900"><b>未写入简历的能力缺口：</b>{content.excluded_gaps.join('、')}</div>}
        </article>
      </div>

      <div>
        <p className="text-sm font-bold tracking-[.16em] text-coral">面试引导</p>
        <h2 className="mt-3 text-3xl font-black">围绕真实经历准备回答</h2>
        <article className="mt-6 rounded-2xl bg-ink p-6 text-white md:p-8"><p className="text-sm text-white/55">约 {guide.self_introduction.duration_seconds} 秒自我介绍草稿</p><p className="mt-4 whitespace-pre-wrap leading-8">{guide.self_introduction.text}</p></article>
        <div className="mt-5 space-y-4">{guide.questions.map((question, index) => <article className="rounded-2xl border border-black/10 bg-white p-6" key={question.id}><p className="text-sm font-bold text-coral">问题 {index + 1}</p><h3 className="mt-2 text-lg font-bold">{question.question}</h3><p className="mt-3 text-sm leading-6 text-black/55">为什么会问：{question.why_asked}</p><p className="mt-2 text-sm text-sage">回答时注意：{question.rubric.join(' · ')}</p></article>)}</div>
        {guide.project_answers.length > 0 && <div className="mt-8"><h3 className="text-xl font-bold">项目追问与回答框架</h3><div className="mt-4 space-y-4">{guide.project_answers.map((answer, index) => <article className="rounded-2xl bg-cream p-6" key={`pa-${index}`}><h4 className="font-bold">{answer.question}</h4><p className="mt-3 text-sm leading-7 text-black/70">{answer.answer}</p><p className="mt-3 text-sm text-sage">继续追问：{answer.follow_ups.join(' / ')}</p></article>)}</div></div>}
        {guide.common_answers.length > 0 && <div className="mt-8"><h3 className="text-xl font-bold">常见问题回答框架</h3><div className="mt-4 grid gap-4 md:grid-cols-2">{guide.common_answers.map((answer, index) => <article className="rounded-2xl border border-black/10 bg-white p-6" key={`ca-${index}`}><h4 className="font-bold">{answer.question}</h4><p className="mt-3 text-sm leading-7 text-black/70">{answer.answer}</p>{answer.follow_ups.length > 0 && <p className="mt-3 text-sm text-sage">可以继续准备：{answer.follow_ups.join(' / ')}</p>}</article>)}</div></div>}
        <div className="mt-8 rounded-2xl border border-sage/20 p-6"><h3 className="text-xl font-bold">面试前准备</h3><ol className="mt-4 space-y-3 text-sm leading-6">{guide.preparation_plan.map((step, index) => <li className="flex gap-3" key={`pp-${index}`}><b className="text-sage">{index + 1}.</b><span>{step}</span></li>)}</ol></div>
        {guide.risk_reminders.length > 0 && <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-6 text-amber-900"><h3 className="font-bold">真实性提醒</h3><ul className="mt-3 space-y-2 text-sm leading-6">{guide.risk_reminders.map((reminder, i) => <li key={`rr-${i}`}>• {reminder}</li>)}</ul></div>}
      </div>

      <div className="rounded-2xl bg-amber-50 p-5 text-sm leading-6 text-amber-900">{result.notices.map((notice, i) => <p key={`nt-${i}`}>• {notice}</p>)}</div>
    </div>
  </section>
}

function SummaryList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return <div className="rounded-2xl border border-black/10 bg-white p-5"><h3 className="font-bold">{title}</h3>{items.length ? <ul className="mt-3 space-y-2 text-sm leading-6 text-black/65">{items.map((item, i) => <li key={`sl-${i}`}>• {item}</li>)}</ul> : <p className="mt-3 text-sm text-black/45">{empty}</p>}</div>
}
