import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { History } from '../pages/History'

const index = {
  generated_at: '2026-09-17T00:00:00Z',
  groups: [
    {
      source: 'model',
      label: '真实模型样本',
      note: '经真实 Provider 的 v3 管线生成',
      items: [{
        id: 'model-1', direction: 'mechanical', direction_label: '机械',
        title: '机械设计助理工程师', bullet_count: 2, writer_source: 'model', bundle_status: 'ready',
        projects: [{ organization: '虚构理工大学', role_title: '项目成员', section: '项目/科研/竞赛', bullets: ['使用 SolidWorks 完成夹具建模', '输出装配图'] }],
        files: { json: '/generated-samples/model-1.json' },
      }],
    },
    {
      source: 'authored',
      label: '本地作者样本',
      note: '由本机撰写并渲染',
      items: [
        {
          id: 'authored-1', direction: 'computer', direction_label: '计算机',
          title: '后端开发实习生', bullet_count: 1,
          projects: [{ organization: '虚构理工大学', role_title: '后端负责人', section: '项目/科研/竞赛', bullets: ['使用 Spring Boot 实现失物登记接口'] }],
          files: { json: '/generated-samples/authored-1.json', html: '/generated-samples/authored-1.html', docx: '/generated-samples/authored-1.docx' },
        },
        {
          id: 'authored-2', direction: 'ai', direction_label: 'AI',
          title: '算法实习生', bullet_count: 1,
          projects: [{ organization: '虚构理工大学', role_title: '模型训练成员', section: '项目/科研/竞赛', bullets: ['使用 PyTorch 训练图像分类模型'] }],
          files: { json: '/generated-samples/authored-2.json' },
        },
      ],
    },
  ],
}

function renderHistory() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><History /></MemoryRouter>
    </QueryClientProvider>,
  )
}

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/generated-samples/index.json')) {
      return new Response(JSON.stringify(index), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
}

test('生成记录按来源和方向分类展示样本', async () => {
  stubFetch()
  renderHistory()
  expect(await screen.findByRole('heading', { name: '真实模型样本' })).toBeVisible()
  expect(screen.getByRole('heading', { name: '本地作者样本' })).toBeVisible()
  expect(screen.getByText('机械设计助理工程师')).toBeVisible()
  expect(screen.getByText('后端开发实习生')).toBeVisible()
  expect(screen.getByText('算法实习生')).toBeVisible()
})

test('生成记录可展开正文并按方向筛选', async () => {
  stubFetch()
  renderHistory()
  await screen.findByText('后端开发实习生')
  await userEvent.click(screen.getAllByRole('button', { name: /查看内容/ })[0])
  expect(await screen.findByText('使用 SolidWorks 完成夹具建模')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: '计算机' }))
  expect(screen.getByText('后端开发实习生')).toBeVisible()
  expect(screen.queryByText('算法实习生')).not.toBeInTheDocument()
  expect(screen.queryByText('机械设计助理工程师')).not.toBeInTheDocument()
})
