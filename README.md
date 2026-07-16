# AI Job Coach MVP

面向机械、制造业和生物医药工程求职者的本地可运行全流程 Demo：事实受控简历、JD 匹配、投递、模拟面试、演示额度和顾问工作台。默认使用 Mock AI、Disabled Payment Provider 和本地私有文件存储，不需要外部密钥、Docker、Redis 或外部数据库。MVP-1 不提供支付、回调或退款接口。

JD 结构化、匹配解释、定制简历和面试题统一通过结构化 LLM Provider。默认 `LLM_PROVIDER=mock`，结果稳定且可离线测试；如需切换兼容 Chat Completions 的服务，在 `.env` 设置 `LLM_PROVIDER=compatible`、`LLM_API_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。真实 Provider 配置不完整、超时或返回无效 JSON 时会安全回退到 Mock；确定性评分与 Fact Guard 始终在本地执行，AI 文本不会被直接当作已验证事实。

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

## 数据保留与维护任务

用户最近活动会延长默认 180 天保留截止时间。用户提交删除申请超过 7 天，或普通用户保留期到期后，维护任务可以清理文件和个人内容；明确发布日期超过 45 天的活动岗位会标记为过期，但不会删除历史投递。

先执行只读预览：

```bash
apps/api/.venv/bin/python scripts/maintenance.py
```

确认候选数量后再显式执行：

```bash
apps/api/.venv/bin/python scripts/maintenance.py --execute
```

正式环境应通过 cron、systemd timer 或 Windows 任务计划程序每天调用一次 `--execute`。命令只输出汇总计数，不输出完整简历、JD 或密钥。相关阈值由 `DATA_RETENTION_DAYS`、`DELETION_GRACE_DAYS` 和 `JOB_STALE_DAYS` 配置。

## Demo 账号

以下账号仅用于本地虚构演示，密码均为 `ChangeMe123!`：

| 角色 | 邮箱 |
|---|---|
| 管理员 | `admin@example.test` |
| 顾问 | `advisor@example.test` |
| 用户 | `user@example.test` |

种子脚本给 Demo 用户发放 20 次匹配、20 次定制简历、40 次辅助投递和 2 次模拟面试额度。管理员也可通过 `POST /api/admin/quotas/grant` 发放/调整额度；必须填写原因和幂等键并写入审计日志。

## 数据与边界

上传支持 DOCX（含表格文字）和文本型 PDF（扫描 PDF 不支持 OCR）。上传后可生成带“建议稿”标识的岗位方向分析；用户确认事实后，系统可按方向搜索词读取工程类公开企业职位合集、指定 Greenhouse 或 Lever 企业公开职位接口，也可使用本地受控样例。公开来源读取失败时会明确提示并回退到本地样例，入库岗位仍需用户打开来源人工核对。

批准后的岗位定制版本会按 JD 相关度排列已确认事实，保留逐条 `source_fact_ids`，可下载 DOCX，也可预览/下载单页 HTML 后通过浏览器打印 PDF。模拟面试包含约 90 秒自我介绍草稿、项目/经历回答、追问、常见问题框架、准备计划和真实性提醒。系统不保存招聘平台密码、不绕过登录/验证码、不执行无人值守投递，也不承诺 Offer。原始上传、SQLite 与导出文件位于被 Git 忽略的 `var/`。

Greenhouse 的企业标识是公开招聘页 URL 中 `boards/` 后的 token；Lever 的企业标识是 `jobs.lever.co/` 后的 site。系统只读取公开 JSON 接口，不抓取需要登录或验证码的平台页面。

模拟面试支持按岗位生成题目、保存真实回答、提交顾问六维评分并查看复盘任务。设置页可下载完整个人数据 JSON；账号清理会删除原始与导出文件，并擦除事实库、JD、投递备注和面试回答等派生个人内容。管理员可在账号清理页处理用户申请，并在系统状态页查看 Provider 配置完整性和维护任务预览；页面从不显示密钥值。

系统允许纠正解析事实和加入真实完成的个人/课程/岗位实践项目，但不生成虚构雇主、任职、奖项、证书或冒用他人成果。普通用户提交定制简历后须由被分配顾问审核，事实检查和审核均通过后才能导出或进入正式投递队列。详见 [`docs/resume-integrity.md`](docs/resume-integrity.md)。

外部简历优化项目的参考范围、许可证注意事项和安全适配见 [`docs/integrations.md`](docs/integrations.md)。

## 生产迁移

笔记本/WSL 仅用于开发和少量授权测试，不应公网暴露。正式运营应部署到 HTTPS Linux 服务，将 `DATABASE_URL` 切换为 PostgreSQL、将 Storage Provider 切换为私有对象存储，并配置真实 LLM Provider、密钥管理、备份及监控。支付系统整体推迟到 MVP-2。Alembic 迁移不依赖 SQLite 专有路径。
