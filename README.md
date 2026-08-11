# AI Job Coach MVP

面向机械、制造业和生物医药工程求职者的本地可运行全流程 Demo：结构化事实、JD 匹配、学习目标、蓝图/可投递双版本简历、投递渠道、模拟面试、演示额度和顾问工作台。默认使用 Mock AI、Disabled Payment Provider 和本地私有文件存储，不需要外部密钥、Docker、Redis 或外部数据库。MVP-1 不提供支付、回调或退款接口。

JD 结构化、匹配解释、事实提取、学习目标、定制简历、面试指南和邮件草稿统一通过结构化 LLM Provider。默认 `LLM_PROVIDER=mock`，结果稳定且可离线测试；如需使用 DeepSeek，在被 Git 忽略的 `.env` 中设置 `LLM_PROVIDER=compatible` 与 `LLM_API_KEY`，并按需调整 `LLM_MODEL_CHEAP`、`LLM_MODEL_STRONG` 和 `LLM_MAX_OUTPUT_TOKENS`。旧的 `LLM_MODEL` 仍可作为两个档位的共同兜底。真实 Provider 配置不完整、超时、返回无效 JSON 或关键内容为空时会安全回退到 Mock；确定性评分与 Fact Guard 始终在本地执行，AI 文本不会被直接当作已验证事实。不要把密钥写入命令、代码、文档或日志。

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
python -m alembic upgrade head
python ../../scripts/seed_demo.py
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

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

完整测试脚本会强制使用 Mock Provider，避免消耗真实额度或让外部服务波动影响回归结果。真实 Provider 验收应使用虚构数据单独执行，且不得输出密钥、完整 Prompt 或完整简历。

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

## 投递渠道导入

渠道是公司级招聘页、表单或邮箱，不是具体岗位源。仓库不分发任何第三方渠道清单；运营者确认来源许可后，把 CSV/XLSX 放在被 Git 忽略的 `data/channel-imports/`。先预览计数：

```bash
apps/api/.venv/bin/python scripts/import_channels.py \
  data/channel-imports/licensed-channels.xlsx \
  --source licensed_operator_file
```

确认新增、更新和拒绝原因后追加 `--execute`。脚本支持 `--mapping` 列名映射，只输出统计，不打印完整渠道或邮箱。招聘页域名入库后可供 `public_jsonld` 读取，但 HTTPS、DNS 公网地址、端口、robots、重定向和响应大小保护仍全部生效。详见 [`docs/integrations.md`](docs/integrations.md)。

## Demo 账号

以下账号仅用于本地虚构演示，密码均为 `ChangeMe123!`：

| 角色 | 邮箱 |
|---|---|
| 管理员 | `admin@example.test` |
| 顾问 | `advisor@example.test` |
| 用户 | `user@example.test` |

种子脚本给 Demo 用户发放 20 次匹配、20 次定制简历、40 次辅助投递和 2 次模拟面试额度。管理员也可通过 `POST /api/admin/quotas/grant` 发放/调整额度；必须填写原因和幂等键并写入审计日志。

## 数据与边界

上传支持 DOCX（含表格文字）和文本型 PDF（扫描 PDF 不支持 OCR）。解析会提取联系方式、组织、角色、地点和日期；关键字段缺失时先追问，不能静默批量确认。用户确认事实后，系统可按方向搜索词读取工程类公开企业职位合集、指定 Greenhouse 或 Lever 企业公开职位接口、白名单招聘页公开提供的 `JobPosting` JSON-LD，也可使用本地受控样例。公开来源读取失败时会明确提示并回退到本地样例，入库岗位仍需用户打开来源人工核对。

匹配缺口可生成带 JD 证据、产出物和验收标准的学习目标。蓝图简历 `target` 可以展示未达成目标，但每条都显式标记 `achieved=false`；可投递简历 `submittable` 只使用已确认事实。两者都经过逐条、mode-aware Fact Guard 和顾问审核，可下载 DOCX，也可预览/下载单页 HTML 后通过浏览器打印 PDF。模拟面试按事实来源和未达成目标生成约 90 秒自我介绍、六段式项目回答、追问、准备计划和真实性提醒。

投递记录可关联公司招聘页、表单或邮箱。邮件渠道只生成经事实保护的草稿和可选 `mailto:` 链接，由用户手动附加简历并发送；系统不保存招聘平台密码、不绕过登录/验证码、不配置 SMTP、不执行无人值守或批量投递，也不承诺 Offer。原始上传、SQLite、导出文件和渠道导入原文件均位于被 Git 忽略的目录。

Greenhouse 的企业标识是公开招聘页 URL 中 `boards/` 后的 token；Lever 的企业标识是 `jobs.lever.co/` 后的 site。系统只读取公开 JSON 接口，不抓取需要登录或验证码的平台页面。

如需读取其他企业或 ATS 的公开招聘详情页，可在 `.env` 的 `JOB_SOURCE_ALLOWED_HOSTS` 中加入已经确认允许访问的域名（多个域名用逗号分隔，支持 `*.example.com`），或导入安全校验通过的 `career_page` 渠道，再输入最终 HTTPS URL。系统会检查域名、公开 IP、`robots.txt`、响应类型和大小，只解析标准 `JobPosting` 数据；不跟随重定向，也不使用 CSS 选择器抓取任意页面。

模拟面试支持按岗位生成题目、保存真实回答、提交顾问六维评分并查看复盘任务。设置页可下载完整个人数据 JSON；账号清理会删除原始与导出文件，并擦除事实库、JD、投递备注和面试回答等派生个人内容。管理员可在账号清理页处理用户申请，并在系统状态页查看 Provider 配置完整性和维护任务预览；页面从不显示密钥值。

系统允许纠正解析事实和加入真实完成的个人/课程/岗位实践项目，但不生成虚构雇主、任职、奖项、证书或冒用他人成果。普通用户提交定制简历后须由被分配顾问审核，事实检查和审核均通过后才能导出或进入正式投递队列。详见 [`docs/resume-integrity.md`](docs/resume-integrity.md)。

外部简历优化项目的参考范围、许可证注意事项和安全适配见 [`docs/integrations.md`](docs/integrations.md)。

## 生产迁移

笔记本/WSL 仅用于开发和少量授权测试，不应公网暴露。正式运营应部署到 HTTPS Linux 服务，将 `DATABASE_URL` 切换为 PostgreSQL、将 Storage Provider 切换为私有对象存储，并配置真实 LLM Provider、密钥管理、备份及监控。支付系统整体推迟到 MVP-2。Alembic 迁移不依赖 SQLite 专有路径。
