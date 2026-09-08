> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

双轨生成能力从同一目标画像与素材快照生成求职版和目标蓝图 Plus；允许无已确认素材的 AI 扩写草稿，生成文案与用户已确认事实始终分开保存。

## ADDED Requirements

### Requirement: One request creates one paired resume bundle
系统 SHALL 对每个成功生成请求创建一个 ResumeBundle，并在同一快照下生成恰好一份 `submittable` 和一份 `target` ResumeVersion。重复的幂等请求 MUST 返回同一 bundle。

#### Scenario: Generate from a single target profile
- **WHEN** 用户用已确认素材和有效目标画像创建简历包
- **THEN** 系统异步生成同源双版本，并可通过 bundle 查询各自状态与 id

#### Scenario: Replay the same request
- **WHEN** 客户端使用相同幂等键和相同请求内容重试
- **THEN** 系统不重复扣减资源或调用模型，并返回原简历包

### Requirement: Model output contains copy only
系统 SHALL 基于同一输入快照和内容合同生成求职版与蓝图 Plus 的结构化文案，不规定合并或分别调用模型。模型 SHALL 负责内容选择、表达和扩写建议，并提出经历、事实或岗位要求引用。系统 MUST 本地校验引用与经历归属，维护稳定 bullet ID、锁定状态、事实状态及固定章节顺序。模型 MUST NOT 生成文件、排版参数或创建稳定 ID；局部重生成允许引用已有 ID 定位内容。

#### Scenario: Assemble model copy into a stable resume
- **WHEN** 模型返回两版经历引用和 bullet 文本
- **THEN** 系统本地写入稳定 bullet ID、来源归属、`achieved`、`verification_status`、锁定状态和固定章节顺序后再保存版本

#### Scenario: A suggested experience has no existing counterpart
- **WHEN** AI 扩写建议没有对应的现有经历
- **THEN** 系统将其保存为独立建议条目，保留 `ai_generated` 和 `achieved:false`，不得强挂到任意已有经历

#### Scenario: A valid reference accompanies an unsupported addition
- **WHEN** 文案引用有效事实 ID，但同时补充来源没有支持的主张
- **THEN** 系统保留 AI 扩写状态，不因 ID 有效而把整条文案视为已确认事实

### Requirement: Studio resumes allow AI expansion
新生成的工作台 v3 简历 SHALL 允许补充原事实中不存在的主张。系统 MUST 保留 `verification_status=ai_generated` 作为内部来源状态，MUST NOT 自动写成用户已确认事实，但不得在工作台、导出和指南显示“待核验”标记。缺少事实支持 SHALL 仅产生提示，不阻止预览和导出。

#### Scenario: Model adds a metric
- **WHEN** 模型补充原素材中没有的量化成果，且来源归属和版面检查通过
- **THEN** 系统保留该要点及新增主张，保留内部 AI 来源状态且不显示“待核验”标记，并允许生成、预览和导出

#### Scenario: Generate without confirmed facts
- **WHEN** 用户已绑定有效目标画像但尚无已确认素材
- **THEN** 系统允许生成不带“待核验”展示标识的双轨草稿

#### Scenario: Reference another user's fact
- **WHEN** 模型引用不属于当前生成上下文的事实 ID
- **THEN** 来源归属门禁拒绝该引用，不因允许扩写而放行

### Requirement: Blueprint Plus represents future target content visibly
蓝图 Plus SHALL 同时包含适用的真实事实和未达成目标。每个未来要点 MUST 引用目标 requirement、保持 `achieved:false` 并在正文显示轻量 `*`；渲染页脚 MUST 解释该标记表示尚未形成可核验经历。

#### Scenario: Render a future certificate target
- **WHEN** 蓝图包含尚未取得且有目标要求依据的证书目标
- **THEN** 该要点携带目标来源、保持 `achieved:false` 并显示 `*`；求职版若有相关 AI 扩写，亦不得将其标为已取得或已确认事实

#### Scenario: Confirm a previously unachieved target
- **WHEN** 用户补充证据并确认蓝图目标已经真实完成
- **THEN** 系统把对应内容转为已确认事实，并允许下一次真实能力简历无标记地使用它

### Requirement: Automatic repair responds to content gate failures
系统 SHALL 按“本地整理上下文、双版本写作、本地组装与内容校验、必要的定向修复、本地渲染与文件检查”执行生成。自动文案修复 SHALL 由本地内容硬门禁失败触发，仅影响相关未锁定内容；解释性评分偏低 MUST NOT 单独触发自动重写。无需修改文案的格式或转换故障 SHALL 仅由本地导出阶段处理；实际内容容量溢出按导出规格的独立内容调整流程处理。最终交付的简历内容 MUST 通过内容门禁；本地回退内容通过时标为 `degraded`，仍不通过时标为 `failed`。修复无法消除失败项时 MUST 结束并回退或失败，不得无限重试或以追求分数为由循环生成。本要求不规定固定修复轮数或模型调用预算。

#### Scenario: Advisory quality issues do not force rewriting
- **WHEN** 首稿通过内容硬门禁，但 critic 指出表达重复或岗位相关性不足
- **THEN** 系统记录受影响要点和改进建议，不自动重写；用户可主动选择局部重生成

#### Scenario: A content gate failure requires targeted repair
- **WHEN** 本地检查发现未锁定要点存在非法来源引用
- **THEN** 系统只针对该失败项修复并重新校验，保留其他内容和锁定状态，在质量报告中记录修复历史；仍不合格时不得以 degraded 交付

#### Scenario: External model remains unavailable
- **WHEN** 外部模型重试后仍不可用
- **THEN** 本地基础版本通过内容门禁时简历标为 degraded，否则生成任务失败；各导出格式仍须独立通过文件门禁，并明确显示对应的降级或失败原因

### Requirement: Users can edit and selectively regenerate
用户 SHALL 能按 bullet、section 或整份简历重生成，锁定的 bullet MUST 在全局重生成中保持不变。任何编辑或重生成 MUST 重跑事实和质量门禁，并使旧内容哈希对应的指南过期。

#### Scenario: Regenerate one unlocked bullet
- **WHEN** 用户只重生成一个未锁定要点
- **THEN** 系统仅替换该要点，固定其原经历归属并校验来源，保留其余内容，重新计算版本质量与哈希

#### Scenario: Regenerate a resume containing a locked bullet
- **WHEN** 用户锁定要点后重生成整份简历
- **THEN** 本地组装保留该要点的 ID、内容、位置和经历归属，不重复追加；模型提出的跨经历事实拼接不得被接受

### Requirement: Production generation survives request and worker interruption
小范围真实用户试用环境 SHALL 通过独立 worker 和 PostgreSQL 持久任务执行生成。API MUST 在持久化任务、输入快照和额度预留后立即返回 `202`，不得要求浏览器连接保持到生成结束。任务领取、续租和结果提交 MUST 使用 claim token；相同幂等键的重放 MUST NOT 重复结算额度或创建交付结果。

#### Scenario: User closes the page after queuing
- **WHEN** 用户收到 queued 任务后关闭网页并稍后重新登录
- **THEN** worker 继续执行，工作台从服务器恢复同一任务及结果

#### Scenario: Claimed worker stops heartbeating
- **WHEN** running 任务连续 90 秒没有续租
- **THEN** 另一个 worker 可原子领取并继续处理，旧 worker 不能覆盖新结果

#### Scenario: Idempotent request is replayed
- **WHEN** 客户端以相同幂等键和相同输入重放创建请求
- **THEN** 系统返回原任务，不重复调用业务生成或结算额度

#### Scenario: Same key carries different input
- **WHEN** 客户端使用已有幂等键提交不同输入快照
- **THEN** 系统返回 `409 IDEMPOTENCY_CONFLICT`
