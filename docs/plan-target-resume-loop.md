# 目标简历闭环实施计划

> 交付对象：Codex。本文是唯一执行依据，按阶段顺序实施，每阶段跑测试后再进入下一阶段。
> 建立时间：2026-08-11

## 0. 产品决策记录（已由产品负责人确认）

> **开工前先读 `PROJECT_SPEC.md` §27。** 本计划与 `PROJECT_SPEC.md` §21.4、§22 的原意图相反，§27 是正式裁决记录；`AGENTS.md` 已声明本文件在相关范围内优先。不要按 §21.4/§22 的原文否掉本计划。

1. **两类简历产物**。系统不再只产出「不超过原始简历」的一份简历，而是两种：
   - **蓝图简历（`kind="target"`）**：内容 = 已确认事实 + **尚未达成的能力目标**。能力水平**高于**原始简历，用途是当学习靶子。
   - **可投递简历（`kind="submittable"`）**：内容 = 只有已确认事实，等于用户当下真实水平。
2. **蓝图简历是否投递，由使用者自行决定，系统不做硬阻断**。不得因为存在未达成条目而禁止导出、禁止提交审核或禁止进投递队列。
3. **但必须逐条记录 `achieved` 状态**。理由是功能性的，不是限制性的：阶段 6 的面试指南必须知道哪些项目用户还没真做过，才能针对性准备并提示哪些追问会被问穿。
4. 投递动作前，前端**一次性**展示该版本的未达成条目数与清单，不重复劝阻。
5. `ResumeFact` 允许扩表加结构化字段。
6. LLM 接 **DeepSeek**，按任务分档。

## 1. 概念模型

```
原始简历 ──解析──> ResumeFact(provenance="original_resume")
                        │
市场 JD ──解析──> Job ──┴──> Match(确定性打分) ──> gaps
                                                    │
                                          CapabilityTarget（未达成能力目标）
                                                    │
                        ┌───────────────────────────┴────────────┐
                        ↓                                        ↓
        蓝图简历 kind="target"                       用户去学，提交产出物
        已确认事实 + 未达成目标                                  ↓
        每条带 achieved 标记                        目标 status="achieved"
                        │                                        ↓
                        │                     ResumeFact(provenance="learned",
                        │                                verification_status="user_confirmed")
                        │                                        ↓
                        └──────────> 可投递简历 kind="submittable" 自动长大
                                                    ↓
                                            投递（用户自行决定投哪份）
                                                    ↓
                                        获得面试 ──> 面试指南
                                                     含每个项目的过程回答
                                                     learned 项目单独话术
```

## 2. 阶段 0：数据层（**已完成，代码已在工作区**）

已改动文件，Codex 不需要重做，直接在此基础上继续：

**`apps/api/app/models/entities.py`**
- `ResumeFact` 新增：`organization` `role_title` `location` `start_date` `end_date`（均 `String`，默认 `""`，日期用 `YYYY-MM` 或 `YYYY-MM-DD` 文本，未知留空**不得由 AI 猜测**）、`provenance`（`String(20)`，默认 `"original_resume"`，取值 `original_resume` / `learned` / `user_added`）。
- 新增 `CapabilityTarget` 模型，表名 `capability_targets`。字段：`id` `user_id` `job_id` `match_id` `requirement` `category` `severity` `jd_evidence` `deliverable` `acceptance_criteria_json` `estimated_hours` `status`（`pending`/`in_progress`/`achieved`/`abandoned`）`evidence_text` `achieved_fact_id` `achieved_at` `created_at` `updated_at`。
- `ResumeVersion` 新增：`kind`（`String(20)`，默认 `"submittable"`）、`unachieved_count`（`Integer`，默认 `0`）。

**`apps/api/alembic/versions/0004_add_capability_targets.py`**（新建）
- 幂等加列（沿用 `0003` 的 `inspect` 风格），带 `server_default` 以回填存量行。
- 建 `capability_targets` 表 + `ix_capability_targets_user_id` 索引。
- `down_revision = "0003_add_retention_fields"`。

已验证：模型可导入，列已生效。**Codex 第一步应先跑 `alembic upgrade head` 确认迁移可执行**，再继续。

---

## 3. 阶段 1：LLM 层按任务分档 + DeepSeek + 调用日志

先做这一阶段，因为阶段 2/3/5 都依赖它。

### 文件

- `apps/api/app/config.py`
- `.env.example`
- `apps/api/app/providers/llm/runtime.py`
- `apps/api/app/providers/llm/compatible.py`
- `apps/api/app/providers/llm/base.py`

### 规格

**配置分档**。现在 `llm_model` 单一值通吃。改为按任务档位：

```
LLM_PROVIDER=mock                      # mock | compatible | mock_fallback
LLM_API_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=
LLM_MODEL_CHEAP=deepseek-chat          # JD 结构化、匹配解释、追问生成
LLM_MODEL_STRONG=deepseek-chat         # 简历改写、面试指南
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=2
```

保留旧 `LLM_MODEL` 作为两档的兜底默认值，避免破坏现有 `.env`。新增 `Settings.model_for(task: str) -> str`，任务名到档位的映射写成模块级常量：

```python
TASK_TIERS = {
    "jd_normalize": "cheap", "match_explain": "cheap", "clarify": "cheap",
    "resume_rewrite": "strong", "interview_guide": "strong",
}
```

**调用契约**。`BaseLLMProvider.complete()` 增加 `task: str` 参数（必填），Provider 依此选模型。所有调用点传明确任务名。

**JSON 修复兜底**。DeepSeek 支持 `response_format={"type":"json_object"}`，正常路径直接用。仍需一层轻量修复应对截断/包裹：
1. 直接 `json.loads`
2. 剥离 ```json 围栏后重试
3. 截取第一个 `{` 到最后一个 `}` 后重试
4. 全部失败 → 抛结构化错误，由调用方回退确定性结果

修复层放 `apps/api/app/providers/llm/json_repair.py`（新建），纯函数 `loads_lenient(text: str) -> dict`，**必须有单元测试覆盖上述 4 条路径**。

**调用日志**（`PROJECT_SPEC.md` §21.1 要求，当前完全缺失）。每次调用记录：任务名、档位、模型名、耗时毫秒、prompt/completion token 数、是否重试、错误类型。用标准 `logging`，logger 名 `app.llm`。

**硬约束：日志不得包含简历原文、JD 原文、个人信息或 API Key**。只记录长度和 token 数。这是 `PROJECT_SPEC.md` 执行原则第 11 条。

### 验收

- `mock` provider 下所有现有测试仍通过。
- `json_repair` 4 条路径单测通过。
- 新增测试断言日志中不出现被传入的敏感字符串。

---

## 4. 阶段 2：结构化事实提取 + 追问

### 文件

- `apps/api/app/services/resume_parser.py`
- `apps/api/app/api/routes/core.py`（`confirm-facts` 路径）
- `apps/api/app/services/resume_analyzer.py`

### 规格

**当前问题**：`resume_parser.py` 把每行原文包成一个 fact（`value_json = {"text": line}`），4 条正则分类，截断 80 行/30 条，不抽取任何结构化信息。

**改为两段式**：

1. **确定性预处理**（不用 LLM）：分段、去页眉页脚、合并折行。
2. **LLM 结构化抽取**（任务名 `resume_extract`，档位 cheap）。输出 schema：

```json
{
  "contact": {"name": "", "phone": "", "email": "", "city": ""},
  "facts": [
    {
      "category": "education|employment|projects|skills|certificates",
      "label": "简短标题",
      "organization": "", "role_title": "", "location": "",
      "start_date": "YYYY-MM 或空", "end_date": "YYYY-MM 或 至今 或空",
      "text": "该条的完整描述，逐字来自原文，不改写",
      "source_text": "原文对应片段"
    }
  ],
  "missing_information": [
    {"fact_index": 0, "field": "end_date", "question": "这段经历的结束时间是？"}
  ]
}
```

**硬约束**：
- `text` 必须逐字来自原文，抽取阶段**不允许改写或润色**。改写只发生在阶段 3。
- 日期未知就留空，**不得推断**（沿用现有「未知日期保持未知」原则）。
- `contact` 落到 `Resume` 上（新增列或存进已有 JSON 字段，Codex 自行选择并写进迁移 `0005`），不要塞进 fact 列表。

**追问机制（轻量式，阻断点在前端而非后端）**：

- `resume_analyzer.py` 产出的 `missing_information` 从被动字符串列表改为上面的结构化问题列表，持久化到 `Resume` 或独立 JSON 列。
- 新增 `POST /api/resumes/{id}/answer-clarifications`，body 为 `[{fact_id, field, value}]`，写回对应 `ResumeFact` 的结构化字段。
- **修掉现有漏洞**：`POST /resumes/{id}/confirm-facts` 目前是一键批量确认全部 pending 事实，前端按钮叫「确认全部事实」，这让「信息不足必须先追问」变成「一键跳过核实」。改为：该接口拒绝确认**关键字段缺失**的事实（`employment`/`projects` 类缺 `organization` 或 `start_date`），返回 `409` 并列出待补字段。逐条确认接口不受影响。

### 验收

- 新增测试：上传含完整时间轴的 DOCX，断言 `organization`/`start_date` 被正确填充。
- 新增测试：关键字段缺失时 `confirm-facts` 返回 409 且列出字段。
- 新增测试：日期缺失时不被填充为猜测值。

---

## 5. 阶段 3：能力差距转为可执行学习目标

### 文件

- `apps/api/app/services/matcher.py`
- `apps/api/app/services/capability_service.py`（新建）
- `apps/api/app/api/routes/workflow.py`

### 规格

**先修 matcher 的硬编码**。当前 `matcher.py:22-25`：

```python
education_hit = any(x in fact_text for x in ["本科", "硕士", "机械"])
experience = 16 if any(x in fact_text for x in ["项目", "设计", "实习", "维护"]) else 6
```

只对机械类应届生有效。改为：
- `hard_requirements` 维度改为逐条比对 `job.must_have_json`，命中率 × 权重。**`must_have` 未满足必须能触发 `hard_block`**（当前只有轮班冲突和岗位关闭触发，与 `PROJECT_SPEC.md` §22.1 不符）。阈值：`must_have` 命中率 < 50% 时 `hard_block = True`。
- `experience` 维度改为基于 `start_date`/`end_date` 计算真实月数，不再靠关键词。
- 保留「AI 只解释不改分」的既有原则，不要动 `core.py` 里的解释逻辑边界。

**gaps → CapabilityTarget**。当前 `matcher.py:80-84` 产出的是硬编码文案 `f"补充可验证的{k}练习或事实"`，没法照着学。

新增 `capability_service.build_targets(match, job, facts) -> list[dict]`，用 LLM（任务名 `capability_plan`，档位 strong）把每条未满足要求转成可交付物：

```json
{
  "targets": [
    {
      "requirement": "SolidWorks 三维建模",
      "category": "skills",
      "severity": "high",
      "jd_evidence": "JD 原文中要求该项的句子（逐字引用）",
      "deliverable": "完成一个含 8 个以上零件的装配体，输出工程图与爆炸图",
      "acceptance_criteria": ["装配体无干涉检查报错", "工程图含尺寸与公差标注", "导出 STEP 与 PDF"],
      "estimated_hours": 20
    }
  ]
}
```

**硬约束**：`jd_evidence` 必须逐字来自 `job.raw_jd`，服务端校验子串包含，不通过则丢弃该 target 并记日志。这防止 AI 编造岗位要求。

**API**：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/matches/{id}/capability-targets` | 由 match 生成目标，幂等（同 match 已有目标则返回现有） |
| `GET` | `/api/capability-targets` | 列出当前用户目标，支持 `?job_id=` `?status=` 过滤 |
| `PATCH` | `/api/capability-targets/{id}` | 改 `status`；转 `achieved` 时必须带 `evidence_text` |

**达成时的副作用**（`status` → `achieved`）：
1. 校验 `evidence_text` 非空，否则 `422`。
2. 自动创建 `ResumeFact`：`provenance="learned"`、`verification_status="user_confirmed"`、`confirmed_at=now`、`category` 取 target 的 `category`、`value_json.text` 由 `deliverable` + `evidence_text` 组合、`organization` 留空（自主项目）。
3. 回填 `achieved_fact_id`、`achieved_at`。
4. 写审计日志 `capability_target.achieved`。
5. **必须在同一事务内完成**，避免出现 target 已达成但 fact 未建。

配额：沿用现有 `quota_service` 模式，`capability_plan` 计入匹配配额还是独立配额由 Codex 参照现有实现选择，需保持幂等控制。

### 验收

- 新增测试：`must_have` 命中率低触发 `hard_block`。
- 新增测试：`jd_evidence` 不在 `raw_jd` 中的 target 被丢弃。
- 新增测试：目标达成后自动生成 `provenance="learned"` 的已确认 fact，且 `achieved_fact_id` 正确回填。
- 新增测试：达成时不带 `evidence_text` 返回 422。
- 新增测试：跨用户访问他人 target 返回 404。

---

## 6. 阶段 4：Fact Guard 改为 mode 感知 + 逐条溯源

### 文件

- `apps/api/app/services/fact_guard.py`（重写）

### 规格

**当前实现的三个具体漏洞**（全文 22 行）：

```python
ENTITY_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?|CAD|SolidWorks|PLC|六西格玛|证书", re.I)
allowed = " ".join(str(f.value_json) for f in confirmed_facts)   # 全局拼成一个大字符串
```

1. 工具白名单只有 4 个词 —— 写 `Python` 会被放过。
2. `\b` 词边界对中文不可靠。
3. **把所有 fact 拼成一个大字符串做子串包含 —— 跨条目虚假拼接（A 公司的经历 + B 项目的成果）会通过校验**。这是最严重的一条。

**新签名**：

```python
def guard_content(
    content: dict,
    confirmed_facts: list,
    targets: list | None = None,
    mode: str = "submittable",
) -> dict:
    """returns {"status", "issues", "unachieved_count", "items": [...]}"""
```

**逐条校验规则**，对 `content["sections"][].items[].bullets[]` 每一条：

1. 必须有非空 `source_fact_ids` 或 `source_target_ids`，否则 issue「缺少事实来源」。
2. `source_fact_ids` 必须是**当前用户的已确认** fact，否则 issue「引用了未确认或不属于当前用户的事实」。
3. `source_target_ids` **只在 `mode="target"` 时允许**；`mode="submittable"` 下出现即 issue「可投递简历不得引用未达成目标」。target 必须属于当前用户。
4. **允许语料按条构建，不是全局**：该条的 allowed corpus = 它所引用的那几条 fact 的 `value_json.text` + `organization` + `role_title` + `start_date` + `end_date` + `source_text`（target 模式下再并入该 target 的 `deliverable` + `acceptance_criteria`）。这一条修掉漏洞 3。
5. 实体抽取改为三类，不用 `\b`：
   - **数字类**：`\d+(?:\.\d+)?\s*(?:%|％|倍|万|k|K|人|天|月|年|个)?`
   - **英文技术 token**：`[A-Za-z][A-Za-z0-9+#.\-]{1,}`（长度 ≥ 2），排除常见英文虚词白名单
   - **证书类**：正则匹配 `证书|资格证|等级考试|职业资格|CET|PMP|CFA|六西格玛|绿带|黑带`
   每个抽出的实体若不在该条的 allowed corpus 中 → issue。
6. `mode="target"` 下，引用了 target 的条目必须带 `achieved: false`，否则 issue「未达成条目缺少 achieved 标记」；统计进 `unachieved_count`。

**状态判定**：
- `mode="submittable"`：有 issue → `"blocked"`，否则 `"passed"`。
- `mode="target"`：**引用 target 造成的「超出现状」不算 issue**（这是蓝图简历的正常内容）；只有规则 1/2/4/5/6 的违规才算。有违规 → `"blocked"`，否则 `"passed"`。

**同时修掉安全问题**：`resume_generator.py` 里的测试专用开关 `inject_unverified`（写死插入「优化流程并提升效率 30%」）当前经 `workflow.py` 的 `VersionIn` 暴露在公开 API，任何登录用户都能让系统主动生成一条虚假成果。改为：从 Pydantic 请求模型中移除该字段，测试改为直接调用 service 层函数传参。

### 验收

必须有测试覆盖以下每一条：
- 跨条目拼接被拦截（引用 fact A，文案里出现 fact B 的数字 → blocked）。
- `Python` 这类未在旧白名单中的工具名被拦截。
- `submittable` 模式引用 target → blocked。
- `target` 模式引用 target 且带 `achieved:false` → passed，且 `unachieved_count` 正确。
- `target` 模式引用 target 但漏 `achieved` 标记 → blocked。
- 跨用户 fact/target 引用 → blocked。
- `inject_unverified` 不再出现在 OpenAPI schema 中（断言 `/openapi.json`）。

---

## 7. 阶段 5：resume_generator 从排序器改成编辑器

这是「改出能拿到面试的简历」的实质部分。

### 文件

- `apps/api/app/services/resume_generator.py`（重写）
- `apps/api/app/api/routes/workflow.py`（生成与 PATCH 路径）

### 规格

**当前实现**：`resume_generator.py:33-34` 取排序后前 12 条 fact，`text` 逐字成为简历条目；标题写死 `f"{job.title}方向求职简历"`。排序权重是 JD 关键词子串计数。没有 STAR 改写、动词收敛、量化归并、一页控制。

**新 content_json 结构（`content_version: 2`）**：

```json
{
  "content_version": 2,
  "kind": "target",
  "headline": "机械设计工程师",
  "contact": {"name": "", "phone": "", "email": "", "city": ""},
  "sections": [
    {
      "name": "项目经历",
      "items": [
        {
          "organization": "某某大学",
          "role_title": "项目负责人",
          "location": "上海",
          "start_date": "2024-03",
          "end_date": "2024-09",
          "bullets": [
            {
              "text": "主导 8 零件装配体设计，输出工程图与爆炸图",
              "source_fact_ids": ["..."],
              "source_target_ids": [],
              "achieved": true
            }
          ]
        }
      ]
    }
  ]
}
```

**向后兼容**：存量 v1 行（`sections[].items[].text`）不迁移，渲染器与 guard 需保留 v1 读取路径，按 `content_version` 缺失即视为 1 分支处理。

**生成流程**：

1. 入参 `kind`（`"target"` 或 `"submittable"`）。
2. 选料：
   - `submittable`：只取 `verification_status == "user_confirmed"` 的 fact（含 `provenance="learned"` 的，这是闭环长大的关键）。
   - `target`：上述 fact + 该 job 下 `status != "achieved"` 的 CapabilityTarget。
3. 排序：保留现有 `relevance()` 关键词权重作为**初排**，但不再直接截断前 12 条；改为把候选全部给 LLM，由 LLM 在一页预算内取舍。
4. LLM 改写（任务名 `resume_rewrite`，档位 strong）。提示词必须包含以下硬约束，并在服务端二次校验：
   - 每个 bullet **必须**填 `source_fact_ids` 或 `source_target_ids`。
   - **不得引入任何来源事实中不存在的数字、工具名、公司名、证书**。
   - 不得把团队成果写成个人成果；主语是「我」时只描述个人动作。
   - 日期只能来自 fact 的结构化字段，未知留空。
   - 每条 bullet ≤ 45 字，动词开头，同一 section 内动词不重复。
   - 引用 target 的 bullet 必须 `achieved: false`。
5. 一页控制（确定性，不交给 LLM 判断）：按字符数与行数估算，超出预算则**从 `severity` 最低的 target 条目和 `relevance` 最低的 fact 条目开始丢**，不缩小字号。预算常量写在模块顶部便于调整。
6. 生成后立即跑 `guard_content(..., mode=kind)`，把 `status` 写入 `guard_status`、`unachieved_count` 写入版本行。
7. LLM 失败或 guard blocked 时，回退到确定性版本（保留现有 fallback 思路），并在响应里明示 `fallback_used`。

**PATCH 路径**：现有 `PATCH /api/resume-versions/{id}` 已实现重跑 guard、回退 `draft`、删旧导出、写审计。需要更新为：按该行的 `kind` 传 mode，并重算 `unachieved_count`。

### 验收

- 新增测试：`submittable` 版本内容不含任何 `source_target_ids`。
- 新增测试：`target` 版本 `unachieved_count` 与实际未达成 bullet 数一致。
- 新增测试：learned fact 出现在 `submittable` 版本中（闭环长大）。
- 新增测试：LLM 返回带虚构数字的 bullet 时被 guard 拦截并触发回退。
- 新增测试：v1 存量 content_json 仍能被渲染与 PATCH。
- **这是全仓库第一批断言简历文案质量的测试**：至少断言 bullet 长度上限、动词开头、来源非空。

---

## 8. 阶段 6：简历排版统一 A4 + 中文规范

### 文件

- `apps/api/app/services/docx_resume_renderer.py`
- `apps/api/app/services/html_resume_renderer.py`

### 规格

**当前的五个具体问题**：

1. DOCX 用 US Letter 8.5×11in，HTML 预览用 A4 —— 同一份简历两种纸张。
2. 中西文字体都设为 `Arial Unicode MS`，macOS 专有，Windows Word 打开会回退，且不是中文简历常用字体。
3. 只渲染 `headline` + 章节名 + 条目文本：无联系方式抬头、无时间轴、无公司/职位副标题、无项目符号、无右对齐日期。
4. HTML 侧用 JS 强制缩放 `0.78` 挤进一页 —— 把排版问题推给浏览器，DOCX 侧无对应机制。
5. 未达成条目没有视觉标记。

**改法**：

- **纸张统一 A4**：`docx.shared.Mm`，`page_width = Mm(210)`、`page_height = Mm(297)`。页边距上下 `Mm(20)`、左右 `Mm(18)`。
- **字体栈**：正文 `w:eastAsia="微软雅黑"`、`w:ascii/w:hAnsi="Calibri"`；标题 `w:eastAsia="黑体"` 加粗。正文 10.5pt，章节标题 12pt，姓名 18pt。行距 1.15。**不要用 macOS 专有字体**。
- **联系方式抬头**：第一行姓名（大号加粗），第二行 `电话 · 邮箱 · 城市`（居中或左对齐，小一号灰色）。数据来自阶段 2 抽取的 `contact`。
- **条目结构**：每个 item 渲染为
  - 第一行：左侧 `组织名 — 职位`（加粗），右侧 `start_date – end_date`（**用 tab stop 右对齐，不要用空格填充**）
  - 第二行起：bullets，用真正的项目符号段落样式，悬挂缩进
- **未达成条目标记**：`achieved: false` 的 bullet 前加 `[未达成 · 学习目标]` 前缀，字体设为灰色。**这是产品决策 3 的可见落地，不是阻断。**
- **一页控制**：DOCX 侧不做缩放，靠阶段 5 的确定性预算控制条目数。HTML 侧移除 JS 强制缩放 `0.78`，改为与 DOCX 相同的 A4 + 相同预算，保证预览与导出一致。
- 两个渲染器共用一份样式常量，抽到 `apps/api/app/services/resume_style.py`（新建），避免再次出现两种纸张。

### 验收

- 新增测试：解开 DOCX 的 `document.xml`，断言 `w:pgSz` 为 A4 尺寸（11906 × 16838 twips）。
- 新增测试：断言 `w:eastAsia` 不等于 `Arial Unicode MS`。
- 新增测试：`achieved:false` 的 bullet 在 DOCX 与 HTML 中都出现 `未达成` 标记。
- 新增测试：HTML 与 DOCX 渲染同一 content 时，章节数与 bullet 数一致。
- 保留现有 `test_resume_exports.py` 的 HTML 转义断言。

---

## 9. 阶段 7：面试指南生成项目过程回答

### 文件

- `apps/api/app/services/interview_generator.py`（重写 `generate_questions` 与 `guard_interview_guide`）

### 规格

**当前实现**：`project_answers` 是一个通用模板，把 fact 文本套进「背景与目标：面试时先补充这段经历的真实背景…个人行动：只展开自己确实完成的步骤」这种占位话术里，对用户没有实际帮助。

**改为每个项目/工作经历生成六段式过程回答**（任务名 `interview_guide`，档位 strong）：

```json
{
  "project_answers": [
    {
      "fact_id": "...",
      "provenance": "original_resume | learned",
      "question": "请完整介绍这个项目",
      "structure": {
        "background": "项目起因与目标，2 句",
        "my_role": "我在团队中的具体职责与边界",
        "actions": ["我做的第 1 件事", "第 2 件", "第 3 件"],
        "difficulties": "遇到的最难的判断，以及为什么这样取舍",
        "result": "可核对的产物",
        "verification": "面试官若要核对，可以看什么"
      },
      "follow_ups": [
        {"question": "这部分具体是你做的还是同学做的？", "how_to_answer": "...", "risk": "high"}
      ]
    }
  ]
}
```

**`provenance="learned"` 的项目单独话术**（这是产品决策 3 的核心用途）。对这类项目：
- `structure.background` 必须如实定位为**近期自主学习项目**，不得包装成公司或校内课题。
- 必须额外生成 `honesty_script` 字段：一段如实说明「这是我为达到岗位要求最近自己做的项目」的话术。
- `follow_ups` 必须包含 `risk: "high"` 的追问，明确提示哪些问题会问穿深度不足，以及诚实的应对方式（承认边界 + 说明已掌握到什么程度）。
- 指南顶部生成 `exposure_warning`：列出该版本里未达成或新学项目的条目数，提示这些是面试中最可能被深挖的部分。

**硬约束**：
- 所有 `structure` 内容必须可溯源到 fact 的 `value_json.text` / `source_text` / target 的 `deliverable`，不得编造项目细节、数字、团队规模。
- `guard_interview_guide` 同步升级为逐条溯源（与阶段 4 的 `guard_content` 共用实体抽取函数，抽到公共模块避免两份正则）。
- 保留现有 `risk_reminders` 与「本文是练习草稿」的免责声明。

### 验收

- 新增测试：`provenance="learned"` 的 fact 产出的答案含 `honesty_script` 且 `background` 不含公司/学校组织名。
- 新增测试：`exposure_warning` 条目数与 target 版本 `unachieved_count` 一致。
- 新增测试：LLM 编造数字时被 `guard_interview_guide` 拦截。
- 新增测试：每个 project_answer 的 `follow_ups` 至少一条，learned 类至少一条 `risk: "high"`。

---

## 10. 阶段 8：前端

### 文件

- `apps/web/src/pages/CapabilityTargets.tsx`（新建）
- `apps/web/src/pages/Resumes.tsx`
- `apps/web/src/pages/Jobs.tsx` 或投递相关页面
- 路由与导航配置

### 规格

**注意现有代码风格**：前端是极致压缩的单行 JSX（`Resumes.tsx` 有单行 1000+ 字符）。可读性差但一致。**新代码写成正常多行格式**，不要模仿这个风格；不要顺手重排既有文件，避免 diff 噪音。

**学习目标页**：
- 按 job 分组列出 targets，显示 `requirement` / `deliverable` / `acceptance_criteria` / `estimated_hours` / `severity`。
- 状态切换（pending → in_progress → achieved）。
- 转 achieved 时弹出证据输入框，`evidence_text` 必填。
- 达成后提示「已加入事实库，可投递简历已更新」。
- 显示整体进度（已达成 / 总数）。

**简历页双版本**：
- 明确区分两种 `kind`，用不同标签色。蓝图简历标签写「蓝图 · 含未达成目标」，可投递写「可投递 · 全部已确认」。
- 蓝图简历列出未达成条目数，点击可跳到学习目标页。
- 两种版本都可预览、下载、提交审核（**不做禁用**，产品决策 2）。
- 渲染阶段 2 产出的 `missing_information` 追问表单（当前 `resume_analyzer` 的输出前端根本没渲染）。
- 「确认全部事实」按钮改文案与行为：关键字段缺失时展示 409 返回的待补字段列表，引导去补而不是静默失败。

**投递前一次性提示**（产品决策 4）：
- 投递动作前，若该版本 `unachieved_count > 0`，弹一次确认框：列出未达成条目、说明这些内容在面试中会被深挖、给「查看面试指南」和「继续投递」两个出口。
- **确认后不再重复提示**（同一 version + job 组合记住已确认，存 localStorage 或后端标记）。不做二次劝阻。

### 验收

- Vitest：学习目标达成流程（含证据必填校验）。
- Vitest：双版本标签正确渲染，蓝图版本显示未达成数。
- Vitest：`unachieved_count > 0` 时投递弹确认框，确认后不再弹。
- Playwright 端到端：上传简历 → 补追问 → 确认事实 → 匹配 → 生成学习目标 → 达成一项 → 生成可投递简历 → 投递 → 生成面试指南。这条链路替换或扩展现有 `main-flow.spec.ts`。

---

## 11. 阶段 9：文档同步

> **注意：规格层的冲突裁决已前置完成，不在本阶段。** `AGENTS.md` 的优先级声明与 `PROJECT_SPEC.md` §27 的变更记录已经写好，开工前请先读 §27。本阶段只做实现完成后的描述性更新。

- `docs/api.md`：新增 capability-targets 三个接口、`answer-clarifications`、`kind` 参数；阶段 10 的 channels 接口与邮件草稿接口。
- `docs/integrations.md`：阶段 10 的渠道导入格式、白名单联动机制、以及「产品不分发渠道数据」这条边界。
- `docs/product-spec.md`：更新产品闭环描述，与 `PROJECT_SPEC.md` §27 对齐。
- `docs/project-status.md`：更新完成清单；把「简历生成质量」从隐含完成改为本轮实际状态；「国内岗位来源」拆成「岗位级（仍未做）」与「投递渠道级（阶段 10）」两条。
- `.env.example`：阶段 1 的新配置项。
- `README.md`：如启动步骤有变则更新。
- 若实施过程中偏离了 §27 的任何一条裁决，**必须回写 §27**，不得只改代码。

---

## 12. 执行顺序与依赖

```
阶段 0（已完成）
   ↓
阶段 1  LLM 层        ← 阶段 2/3/5/7 都依赖
   ↓
阶段 2  结构化提取 + 追问
   ↓
阶段 3  学习目标      ← 依赖阶段 2 的结构化 fact
   ↓
阶段 4  Fact Guard    ← 依赖阶段 3 的 target 实体
   ↓
阶段 5  简历生成      ← 依赖阶段 4 的 guard 与阶段 2 的结构化 fact
   ↓
阶段 6  排版          ← 依赖阶段 5 的 content_version 2
   ↓
阶段 7  面试指南      ← 依赖阶段 3 的 provenance 与阶段 5 的 unachieved_count
   ↓
阶段 8  前端          ← 依赖以上全部接口
   ↓
阶段 9  文档

阶段 10 投递渠道      ← 独立线，10.1–10.5 可与阶段 3–7 并行
                        10.6 邮件草稿依赖阶段 2 的 contact 与阶段 5 的 DOCX
```

每阶段结束跑 `./scripts/test.sh`，全绿再进下一阶段。阶段 5 之后跑一次完整回归，因为 content 结构变更影响面最大。

## 13. 本轮明确不做

- **国内岗位来源（岗位级）**。现有 5 个 provider 的企业清单全是美国公司。这是独立一条线，需要合法开放接口或授权，不在本轮范围。注意「小纸团」不属于这一项——它是投递渠道源，见阶段 10。
- 不实现绕过登录、验证码、反爬（`PROJECT_SPEC.md` 合规边界）。
- 不动支付（保持 Disabled Provider）。
- 不动邮件/通知 Provider。**阶段 10 的邮件草稿不是发信功能，不需要 SMTP。**
- 不重排既有前端单行 JSX 风格。

---

## 14. 阶段 10：投递渠道（小纸团）

### 14.0 概念定位

「小纸团」是一个**投递渠道数据库**：很多公司的简历投递网址和邮箱。

**关键区分：它不是岗位源。** 现有 5 个 provider 都返回 `DiscoveredJob`（具体岗位：标题、JD、发布时间），而渠道数据是**公司级的投递入口**。两者是不同实体，**不要塞进 `BaseJobProvider`**。

它与 `public_jsonld` 互补而非重复：渠道表提供公司招聘页 URL，而 `public_jsonld` 需要的输入正好是一个 URL。串起来即「渠道给入口 → `public_jsonld` 读该页 JD → 进现有 JD 结构化与匹配链路」。

### 14.1 产品决策记录（已确认）

1. **授权状态不确定** → 产品只实现**导入能力**，**不随代码分发任何第三方渠道数据**。导入的原始文件不得进 Git、不得作为 seed 数据。运营者导入前需自行确认来源许可。
2. **邮箱投递只生成草稿，用户自己发**。系统不配置 SMTP、不提供发信接口、不提供批量入口。
3. **渠道表中的域名自动允许 `public_jsonld` 读取**，但 `public_jsonld` 的其余保护层一层都不能删。

### 14.2 数据模型

新建 `application_channels` 表。迁移 `0006`（若阶段 2 未占用 `0005` 则顺延）。

```
id
owner_user_id   -> users.id, NULLABLE     # NULL = 全局共享；非空 = 该用户私有
company_name, company_aliases_json
channel_type: "career_page" | "email" | "form"
url, email
scope: "campus" | "experienced" | "both"
regions_json, industries_json
source, source_updated_at                  # 渠道最大的问题是失效，必须带更新时间
verify_status: "unverified" | "reachable" | "dead"
dead_reports: Integer, default 0
content_hash                               # 导入去重
notes
created_at, updated_at
```

**`owner_user_id` 设为 nullable 是刻意的**：授权状态不确定，将来无论决定走全局共享还是按用户隔离，都不需要再改表。当前实现按 NULL（全局）读取，查询时用 `owner_user_id.is_(None) | owner_user_id == current_user.id`。

唯一约束：`(company_name 规范化后, channel_type, coalesce(url, email))`。

**隐私边界**：这是**公司数据不是个人数据**，不进 `privacy_service` 的保留期/删除清理链路。在 `privacy_service` 里加一行注释说明为什么排除，防止后来的人误加。唯一例外：`owner_user_id` 非空的行在该用户删除时需一并清理。

`Application` 表加 `channel_id`（nullable，同一迁移完成），投递记录关联实际使用的入口。

### 14.3 导入

`scripts/import_channels.py`（新建）。沿用 `scripts/maintenance.py` 的模式：**默认 dry-run，`--execute` 才写库**。

- 支持 CSV 与 Excel，列名映射配置化（不同来源列名不同）。
- 幂等：重复导入同一文件不产生重复行，只更新 `source_updated_at`。
- 去重按 `content_hash`。
- 输出统计：新增 / 更新 / 跳过 / 拒绝，各类拒绝原因计数。
- **输出中不得打印完整渠道清单或邮箱**，只打印计数（沿用维护脚本的日志约束）。
- 导入文件路径加进 `.gitignore`。

**导入层的安全校验（关键，见 14.4）**：以下值必须在**入库前**拒绝，不能只靠运行时挡：

- 非 HTTPS 的 URL（http 的可入库但 `verify_status="unverified"` 且**不进白名单**）
- IP 字面量作为主机名
- `localhost`、`*.local`、`*.internal`、`*.localdomain`
- 解析到私有/保留网段的域名（复用 `public_jsonld` 已有的 `_ensure_public_addresses`）
- 带 userinfo（`user:pass@`）的 URL
- 非 443 端口
- 邮箱格式非法

### 14.4 与 JSON-LD 白名单联动

`Settings.allowed_job_source_hosts()` 当前只从 env 读逗号分隔值。改为：

```
允许域名 = env 的 JOB_SOURCE_ALLOWED_HOSTS
         ∪ 渠道表中 channel_type="career_page" 且 verify_status != "dead" 的域名
```

- 渠道表可能几千行，需缓存；导入或标记 dead 后失效缓存。
- **`public_jsonld` 的以下保护全部保留，一层都不能删**：强制 HTTPS、端口限 443、拒 IP 字面量、DNS 解析后非私有地址校验、不跟随重定向、robots.txt 校验、2MB 响应截断、Content-Type 白名单。

**这个改动的实质是把「谁能决定可读域名」从 env 交给了导入数据**，所以 14.3 的导入层校验是这一步的前置条件，不是可选项。

### 14.5 渠道 → 岗位

`POST /api/channels/{id}/discover-jobs`：用该渠道的 `url` 走 `public_jsonld`，读到的岗位进现有 Job 链路（含内容哈希去重）。失败沿用现有 fallback 规则，响应明示 `fallback_used` / `source_error`。

### 14.6 邮件草稿

`apps/api/app/services/application_email.py`（新建）。

```python
def build_email_draft(profile, resume_version, job, channel) -> dict:
    """returns {to, subject, body, attachment_hint, mailto_url, warnings}"""
```

- 任务名 `email_draft`，档位 cheap。
- 主题行：`应聘{岗位} - {姓名} - {学校/专业}`，数据来自阶段 2 抽取的 `contact` 与已确认事实。
- 正文三段：① 应聘岗位与来源 ② 2–3 条匹配点 ③ 附件说明与联系方式。
- **每条匹配点必须引用已确认事实**，走阶段 4 的同一套溯源校验。**复用阶段 4 抽出的公共实体抽取函数，不要写第三份正则。**
- `attachment_hint`：提示用户手动附加哪个文件（系统不经手附件发送）。
- `mailto_url`：浏览器 `mailto:` 长度上限约 2000 字符，**正文超长时不生成 `mailto_url`，只返回 `body` 供复制**。这是实际会踩的坑，必须有测试。
- **系统不发送**：不配置 SMTP、不提供发信接口、不提供批量入口。API 只返回草稿文本。

**一个需要你确认的细节（Codex 按下述默认实现，产品负责人可推翻）**：若投递的是蓝图简历（`kind="target"`，含未达成条目），**邮件正文只引用已达成事实**，不把未达成目标写成已有能力；同时在 `warnings` 里提示「附件含 N 条未达成内容，正文只写了已达成部分」。

理由：附件投哪份是使用者的决定（产品决策 0.2），但邮件正文是**系统代笔的文字**，系统不主动替用户宣称未达成的能力。这两件事不冲突。

### 14.7 失效反馈

渠道数据最大的实际问题是失效：网址改版、邮箱停用。

- `POST /api/channels/{id}/report-dead`：用户投递后遇退信或 404 时标记，`dead_reports += 1`。
- 累计 ≥ 3 次自动转 `verify_status="dead"`，**自动退出 14.4 的白名单**。
- 可选：`scripts/maintenance.py` 增加渠道可达性抽检（HEAD 请求、遵守 robots、限速、默认 dry-run）。低优先。

### 14.8 前端

- 渠道列表页：按公司搜索，显示 `channel_type` / `scope` / `source_updated_at` / `verify_status`。
- 失效标记入口。
- 投递队列每条显示入口：`career_page` 可点击跳转，`email` 可复制并「生成邮件草稿」。
- 邮件草稿弹窗：显示主题与正文、复制按钮、`mailto` 按钮（超长时隐藏并提示复制）、`warnings` 展示。

### 14.9 验收

- 导入幂等：同一文件导入两次不产生重复行。
- **导入层安全校验必须逐项有测试**：`127.0.0.1`、`192.168.1.1`、`localhost`、`foo.internal`、`http://`（非 https）、`user:pass@host`、非 443 端口、非法邮箱 —— 全部被拒绝入库。
- 白名单联动：渠道入库后其域名可被 `public_jsonld` 读取；标记 `dead` 后立即不可读。
- `public_jsonld` 现有 4 个安全用例仍全部通过（**不得因为这个阶段放宽任何一层**）。
- 邮件草稿：正文匹配点全部可溯源；引用未确认事实时被拦截。
- 邮件草稿：正文超长时不返回 `mailto_url`。
- 蓝图简历投递时，正文不含未达成条目，`warnings` 含未达成计数。
- 失效反馈累计 3 次自动转 dead。
- 渠道表不进保留期清理；`owner_user_id` 非空的行在用户删除时被清理。

---

## 15. 已在工作区的其他未提交改动（保留，勿回退）


与本计划无关但已完成、质量合格的三个特性，Codex 不要动：

1. **白名单公开招聘页 Provider**：`providers/jobs/public_jsonld.py`（304 行）+ config 的 `job_source_allowed_hosts` + `provider_status` 的 `public_jsonld_configured` + `core.py` 的 provider 正则与来源校验 + `test_job_discovery.py` 的 4 个用例。SSRF/robots/白名单/限流边界完整。
2. **DOCX 渲染抽出为独立服务**：`services/docx_resume_renderer.py`。**阶段 6 会重写这个文件的内容，但保留它作为独立服务的结构。**
3. **用户编辑定制简历版本**：`PATCH /api/resume-versions/{id}` + `Resumes.tsx` 内联编辑器。**阶段 5 会扩展它以支持 kind 与 unachieved_count。**
