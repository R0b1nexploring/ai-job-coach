# AI Job Coach MVP

面向机械、制造业和生物医药工程求职者的本地可运行全流程 Demo：事实受控简历、JD 匹配、投递、模拟面试、演示额度和顾问工作台。默认使用 Mock AI、Disabled Payment Provider 和本地私有文件存储，不需要外部密钥、Docker、Redis 或外部数据库。MVP-1 不提供支付、回调或退款接口。

## 环境

- 推荐 Windows 11 + WSL2 Ubuntu，仓库放在 `~/projects/ai-job-coach`
- Python 3.12+、Node.js 18+、npm 9+
- 不要在同一工作区混用 Windows 与 WSL 生成的 `.venv`/`node_modules`

## Bash 一键启动

```bash
cp .env.example .env
./scripts/dev.sh
```

脚本会检查并安装缺失依赖、运行迁移和种子数据，然后同时启动 API 与 Web。浏览器访问：

- Web：http://localhost:5173
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

也可分别启动：

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
python ../../scripts/seed_demo.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

cd apps/web
npm install
npm run dev -- --host 0.0.0.0
```

## PowerShell 备用方式

请在 Windows 原生仓库中使用，勿在 `\\wsl$` 工作区混装依赖：

```powershell
Copy-Item .env.example .env
.\scripts\dev.ps1
```

## 测试

```bash
./scripts/test.sh
```

PowerShell：`.\scripts\test.ps1`。单独运行 E2E 前先启动前后端，或执行 `cd apps/web && npm run e2e`（Playwright 配置会自动启动服务）。

首次运行 E2E 需安装浏览器：`cd apps/web && npx playwright install chromium`。精简 WSL 镜像若提示缺少 `libnspr4` 等库，再执行 `npx playwright install-deps chromium`。

## Demo 账号

以下账号仅用于本地虚构演示，密码均为 `ChangeMe123!`：

| 角色 | 邮箱 |
|---|---|
| 管理员 | `admin@example.test` |
| 顾问 | `advisor@example.test` |
| 用户 | `user@example.test` |

种子脚本给 Demo 用户发放 20 次定制简历、40 次辅助投递和 2 次模拟面试额度。管理员也可通过 `POST /api/admin/quotas/grant` 发放/调整额度；必须填写原因和幂等键并写入审计日志。

## 数据与边界

上传仅支持 DOCX 和文本型 PDF（扫描 PDF 不支持 OCR）。岗位仅支持人工粘贴、用户公开链接及受控样例；系统不保存招聘平台密码、不绕过登录/验证码、不承诺 Offer。原始上传、SQLite 与导出文件位于被 Git 忽略的 `var/`。

## 生产迁移

笔记本/WSL 仅用于开发和少量授权测试，不应公网暴露。正式运营应部署到 HTTPS Linux 服务，将 `DATABASE_URL` 切换为 PostgreSQL、将 Storage Provider 切换为私有对象存储，并配置真实 LLM Provider、密钥管理、备份及监控。支付系统整体推迟到 MVP-2。Alembic 迁移不依赖 SQLite 专有路径。
