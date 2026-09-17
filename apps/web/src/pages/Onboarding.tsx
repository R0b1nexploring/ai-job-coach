import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../app/AuthContext'
import { ErrorState } from '../components/States'
import { PageHeader } from '../components/ui'
import { clearOnboardingDraft, loadOnboardingDraft, saveOnboardingDraft } from '../utils/onboardingDraft'

type Form = {
  school: string; major: string; graduation_year: number; education_level: string;
  target_cities: string; target_roles: string; target_industries: string;
  accepts_shift: string; accepts_travel: string; accepts_factory: string; consent: boolean;
}
const defaults: Form = { school: '', major: '', graduation_year: 2026, education_level: '本科', target_cities: '杭州', target_roles: '设备工程师,机械助理工程师', target_industries: '制造业', accepts_shift: 'unknown', accepts_travel: 'yes', accepts_factory: 'yes', consent: false }
const stringFields: Array<keyof Form> = ['school', 'major', 'education_level', 'target_cities', 'target_roles', 'target_industries', 'accepts_shift', 'accepts_travel', 'accepts_factory']

function isValidDraft(value: Record<string, unknown>): boolean {
  return stringFields.every((field) => value[field] === undefined || typeof value[field] === 'string')
    && (value.graduation_year === undefined || (typeof value.graduation_year === 'number' && Number.isFinite(value.graduation_year)))
    && (value.consent === undefined || typeof value.consent === 'boolean')
}

export function Onboarding() {
  const [step, setStep] = useState(1)
  const [file, setFile] = useState<File>()
  const [error, setError] = useState<unknown>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const stored = user ? loadOnboardingDraft<Form>(user.id, isValidDraft) : undefined
  const form = useForm<Form>({ defaultValues: { ...defaults, ...stored } })
  useEffect(() => {
    if (!user) return
    const subscription = form.watch((value) => saveOnboardingDraft(user.id, value))
    return () => subscription.unsubscribe()
  }, [form, user])

  const save = async (value: Form) => {
    setError(undefined)
    try {
      await api('/api/profile', { method: 'PUT', body: JSON.stringify({
        ...value,
        target_cities: value.target_cities.split(',').map((x) => x.trim()).filter(Boolean),
        target_roles: value.target_roles.split(',').map((x) => x.trim()).filter(Boolean),
        target_industries: value.target_industries.split(',').map((x) => x.trim()).filter(Boolean),
        accepts_shift: value.accepts_shift === 'unknown' ? null : value.accepts_shift === 'yes',
        accepts_travel: value.accepts_travel === 'yes', accepts_factory: value.accepts_factory === 'yes',
      }) })
      if (file) { const body = new FormData(); body.append('file', file); await api('/api/resumes', { method: 'POST', body }) }
      clearOnboardingDraft(user?.id)
      navigate('/app/resume-studio')
    } catch (reason) { setError(reason) }
  }
  const stepNames = ['基本信息', '求职偏好', '工作条件', '上传简历', '授权确认']
  return <><PageHeader kicker="个人档案" title="建立求职档案" lead="只填写求职需要的信息，草稿会自动保存在当前设备。" />
    <div className="mt-6 grid max-w-3xl grid-cols-5 gap-1" aria-label={`第 ${step}/5 步 · 自动保存草稿`}>{stepNames.map((name, index) => <button type="button" key={name} className={`rounded-lg px-1 py-2 text-center text-[11px] font-medium transition ${index + 1 === step ? 'bg-sage/[0.09] text-sage' : index + 1 < step ? 'text-sage' : 'text-ink-muted'}`} onClick={() => setStep(index + 1)}><span className={`mx-auto mb-1 block h-1 rounded-full ${index + 1 <= step ? 'bg-sage' : 'bg-ink/10'}`} />{name}</button>)}</div>
    <form noValidate className="card mt-5 max-w-3xl space-y-4 p-6 sm:p-8" onSubmit={form.handleSubmit(save)}>
      {step === 1 && <><h2 className="text-xl font-semibold">基本信息</h2><label><span className="label">学校</span><input className="field" {...form.register('school')} /></label><label><span className="label">专业</span><input className="field" {...form.register('major', { required: true })} /></label><label><span className="label">毕业年份</span><input className="field" type="number" {...form.register('graduation_year', { valueAsNumber: true })} /></label></>}
      {step === 2 && <><h2 className="text-xl font-semibold">求职偏好</h2><label><span className="label">目标城市（逗号分隔）</span><input className="field" {...form.register('target_cities')} /></label><label><span className="label">目标岗位（逗号分隔）</span><input className="field" {...form.register('target_roles')} /></label><label><span className="label">目标行业（逗号分隔）</span><input className="field" {...form.register('target_industries')} /></label></>}
      {step === 3 && <><h2 className="text-xl font-semibold">工作条件</h2>{[['accepts_shift','是否接受轮班'],['accepts_travel','是否接受出差'],['accepts_factory','是否接受工厂环境']].map(([name, label]) => <label key={name}><span className="label">{label}</span><select className="field" {...form.register(name as keyof Form)}><option value="unknown">待确认</option><option value="yes">接受</option><option value="no">不接受</option></select></label>)}</>}
      {step === 4 && <><h2 className="text-xl font-semibold">上传简历</h2><p className="text-sm text-ink-secondary">支持 DOCX 和文本型 PDF，最大 10MB；扫描 PDF 暂不支持 OCR。</p><input className="field" type="file" accept=".docx,.pdf" onChange={(event) => setFile(event.target.files?.[0])} />{file && <p className="text-sm text-green-700">已选择：{file.name}</p>}</>}
      {step === 5 && <><h2 className="text-xl font-semibold">授权确认</h2><label className="flex gap-3"><input type="checkbox" {...form.register('consent', { required: true })} /><span className="text-sm">我已阅读隐私说明，同意为本次求职服务处理必要资料；案例展示授权默认不允许。</span></label>{form.formState.errors.consent && <p className="text-sm text-red-600">请确认授权后继续。</p>}</>}
      {error != null && <ErrorState error={error} />}
      <div className="flex justify-between gap-3 border-t border-line pt-5">{step > 1 ? <button type="button" className="btn-secondary" onClick={() => setStep(step - 1)}>上一步</button> : <span />}{step < 5 ? <button type="button" className="btn" onClick={() => setStep(step + 1)}>下一步</button> : <button className="btn">保存并进入工作台</button>}</div>
    </form></>
}
