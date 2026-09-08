import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { ErrorState, Loading } from '../components/States'

export function Dashboard() {
  const quotas = useQuery({ queryKey: ['quotas'], queryFn: () => api<Record<string, number>>('/api/quotas') })
  const report = useQuery({ queryKey: ['weekly'], queryFn: () => api<any>('/api/reports/weekly') })
  if (quotas.isLoading) return <Loading />
  if (quotas.error) return <ErrorState error={quotas.error} />
  return (
    <>
      <p className="badge">本周执行中心</p>
      <h1 className="page-title mt-3">用真实经历生成一页简历</h1>
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <Link to="/app/experience" className="card hover:border-sage">
          <p className="text-sm text-black/50">第一步</p>
          <h2 className="mt-2 text-2xl font-black">完善实习 / 项目</h2>
          <p className="mt-3 text-sm text-black/60">把真实实习和项目记进经历库，这是后面改简历的材料。</p>
        </Link>
        <Link to="/app/jobs" className="card hover:border-sage">
          <p className="text-sm text-black/50">第二步</p>
          <h2 className="mt-2 text-2xl font-black">选一个目标岗位</h2>
          <p className="mt-3 text-sm text-black/60">粘贴 JD 或打开匹配报告，再生成针对这个岗位的简历。</p>
        </Link>
        <Link to="/app/resumes" className="card hover:border-sage md:col-span-2">
          <p className="text-sm text-black/50">第三步</p>
          <h2 className="mt-2 text-2xl font-black">生成一页简历</h2>
          <p className="mt-3 text-sm text-black/60">用已确认的实习和项目改写要点。未达成学习目标会标成灰色，不会假装已经做过。</p>
        </Link>
      </div>
      <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Object.entries({ resume: '定制简历', application: '辅助投递', interview: '模拟面试', match: '免费匹配' }).map(([key, label]) => (
          <div className="card" key={key}>
            <p className="text-sm text-black/50">{label}额度</p>
            <p className="mt-2 text-4xl font-black">{quotas.data?.[key] ?? 0}</p>
          </div>
        ))}
      </div>
      <section className="card mt-6">
        <h2 className="text-xl font-bold">本周周报</h2>
        {report.isLoading ? <p>正在统计…</p> : (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <p>岗位 <b>{report.data?.new_jobs}</b></p>
            <p>已投递 <b>{report.data?.applied}</b></p>
            <p>面试 <b>{report.data?.interview}</b></p>
            <div className="sm:col-span-3"><b>下一步：</b>{report.data?.next_actions?.join('；')}</div>
          </div>
        )}
      </section>
    </>
  )
}
