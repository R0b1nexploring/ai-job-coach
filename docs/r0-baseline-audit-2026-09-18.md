# R0 基线与复用审计（2026-09-18）

对应 tasks 17.1、17.2。本记录只描述审计时的实际代码与测试状态，不代表任何任务已完成。

## 审计环境

| 项 | 值 |
| --- | --- |
| commit | `45e0b8b`（`docs: define complete self-service workflow and deployment roadmap`） |
| 工作区 | 干净，无未提交改动；审计前建立 `backup/pre-r0r1` 分支与 `backup/pre-r0r1-20260918-231336` 标签 |
| 数据库 | PostgreSQL 16.15（本地 `ai_job_coach`），迁移版本 `0010`；代码 head 为 `0011` |
| LLM Provider | `.env` 为 `compatible` 但缺 `LLM_API_KEY`，运行期实际回退 Mock |
| 存储 | `local` |

## 17.1 测试与构建基线

| 命令 | 结果 |
| --- | --- |
| `./scripts/test.sh`（后端 pytest） | 329 passed |
| `./scripts/test.sh`（前端 Vitest） | 43 passed（5 files） |
| `./scripts/test.sh`（Playwright E2E） | 3 passed |
| `cd apps/web && npm run build` | 成功（tsc -b + vite build） |

无既有失败。上述数字为审计基线，后续改动必须在此之上运行相关回归。

## 既有实现证据与差距

### 已存在、应复用

- `ResumeBundleRun` 已具备 claim token、租约、心跳、尝试次数、输入快照、结果引用、公开错误码（`0011`）。
- `claim_bundle_run` / `heartbeat_bundle_run` / `_claimed_bundle_run` 已实现条件更新领取与提交时 claim 校验。
- `QuotaLedger` / `QuotaBalance` / `QuotaReservation` 已实现预留、结算与退款，且有 `uq_quota_ledger_user_type_idempotency`。
- `InterviewGuide` 已按 kind 分离，`queue_guides_for_bundle` 已存在。
- `evaluate_version` 已实现 STAR 结构、占位话术、来源映射、目标误标实测的硬门禁；`evaluate_version_with_critic` 已实现缺维度不补假分、模型不可用回退。
- `build_project_story_inputs`、`design_assumptions`、`open_questions`、`visible_coverage` 诊断已存在。
- `CompatibleLLMProvider` 已区分可重试/不可重试错误，已实现 408/425/429/5xx 判定。

### 差距（本次及后续任务要处理）

| 差距 | 位置 | 归属 |
| --- | --- | --- |
| 没有通用任务表与统一运行状态词汇，领取权只在 `resume_bundle_runs` | 模型层 | 17.2 |
| `process_queued_bundles` 先按状态排序 limit，未在排序前过滤“可领取” | `bundle_service.py:775` | 17.7 |
| 有效租约内的 `generating` 任务仍进入候选批次，可能造成队头阻塞 | `bundle_service.py:775` | 17.7 |
| 零领取时 worker 仍每 2 秒空转，未按“仅成功领取计数”休眠 | `app/worker.py` | 17.7 |
| 双版本结果，指南无独立持久任务 | `bundle_service.py:824`、`interview_guide_service.py` | 17.10 |
| 模型传输无指数退避与 `Retry-After` 支持与两份指南，未识别结束原因（截断/拒绝/空响应） | `providers/llm/compatible.py` | 17.5 |
| 传输重试会追加“JSON 解析失败”提示词，与“传输重试不改提示词”冲突 | `providers/llm/compatible.py:88` | 17.5 |
| 无任务总期限；修复循环以硬门禁失败触发，无语义问题定向修复 | `bundle_service.py:1127` | 17.4、17.8 |
| 语义内容错误只作解释性评审，不触发定向修复 | `quality_service.py` | 17.4 |

### 迁移漂移（审计发现，未在本次修复）

代码 head 为 `0011`，但本地 PostgreSQL 停在 `0010`，查询 `resume_bundle_runs` 会报
`column resume_bundle_runs.task_type does not exist`。该漂移属于部署环境状态，不在 17.1/17.2
的代码范围内；17.2 的新迁移会以“旧库可升级”为前提验证，不依赖该库当前状态。

## 真实模型与规则/mock 的区分

本次基线全部使用 mock Provider 与临时数据库，不能作为真实模型效果的证据。R1 中需要真实模型
对照的部分（17.3、17.4、17.5 的语义修复效果）必须另用虚构材料单独记录。
