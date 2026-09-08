> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

面试指南能力为真实能力简历和蓝图 Plus 分别生成与每个可见要点严格绑定的准备材料，让用户知道如何证明真实经历，以及哪些未来目标目前不能冒充已完成。

## ADDED Requirements

### Requirement: Every resume bundle receives two version-bound guides
系统 SHALL 在两版内容门禁通过、bundle 进入 ready 或可交付 degraded 后，为求职版和蓝图 Plus 分别自动排队生成指南，不等待 PDF 成功，也不要求用户打开指南才开始生成。每份指南 MUST 绑定具体 resume version、目标画像和内容哈希，不得使用同一份泛化指南替代。指南任务的失败 MUST NOT 使已完成的简历失效。

#### Scenario: Resume bundle becomes ready
- **WHEN** 双轨简历通过内容门禁并进入 ready 或可交付 degraded
- **THEN** 系统为两个版本分别排队生成指南，并在 bundle 中返回指南状态

#### Scenario: PDF is unavailable after content delivery
- **WHEN** 两版内容已可交付，但 PDF 转换失败
- **THEN** 两份指南仍可独立生成，PDF 失败不取消指南任务

### Requirement: The submittable guide covers every visible claim
真实能力版指南 MUST 为简历中每个可见 bullet 生成来源绑定的 claim card，包含主问题、连续追问、六段式讲法、个人贡献边界、核验材料和危险说法；并 SHALL 提供 60/90 秒自我介绍、JD 专业与行为题、岗位动机、反问清单和面试前检查表。

#### Scenario: Generate a guide for three resume bullets
- **WHEN** 求职版含三个均有已确认事实支持的可见 bullet
- **THEN** 指南恰好覆盖三个 bullet id，且每张卡引用该 bullet 的事实来源

### Requirement: The blueprint guide exposes every future-item risk
蓝图指南 MUST 覆盖每个 `achieved:false` 要点，列出可能被问穿的问题、当前能够诚实回答的边界、缺少的证据和完成后应具备的答法。系统 MUST NOT 生成把未完成内容描述为已完成的回答。

#### Scenario: Blueprint contains an unearned award target
- **WHEN** 蓝图含一项尚未取得的奖项目标
- **THEN** 指南明确其未达成状态、当前不可声称拥有，并列出未来需要的核验证据

### Requirement: Guide coverage and grounding are hard gates
每张卡 MUST 引用绑定版本中的 bullet id，可见 bullet 覆盖率 MUST 为 100%。事实型卡片 MUST 引用该 bullet 的实际事实来源；未确认素材与 AI 扩写卡 SHALL 使用实际存在的素材或目标引用，不强求不存在的事实 ID。无事实来源的扩写 MUST 保留未确认语义，不得伪造来源或将内容描述为已验证经历；指南也不得新增简历与来源之外的用户事实。非法来源、错误状态或漏项 MUST 阻止指南进入 ready，而缺少已确认事实本身不得阻止为 AI 扩写生成准备指南。

#### Scenario: An AI-expanded bullet has no confirmed fact
- **WHEN** 求职版包含没有已确认事实支持的 AI 扩写要点
- **THEN** 指南绑定该 bullet，提供诚实表达边界与需补充的证据，不伪造事实 ID、不把扩写当作已完成经历，也不显示“待核验”标签

#### Scenario: Model omits one resume bullet
- **WHEN** 生成结果没有覆盖绑定版本中的一个可见 bullet
- **THEN** 系统触发修复或安全回退，并在补齐前不把指南标为 ready

### Requirement: Guides become stale after resume changes
当绑定简历内容哈希变化时，现有指南 MUST 标为 stale，并 SHALL 保留为历史记录直到新指南生成完成。

#### Scenario: User edits a resume bullet
- **WHEN** 用户保存对已有关联指南的简历修改
- **THEN** 旧指南立即显示过期，新指南必须基于新内容哈希生成

### Requirement: First release delivers guides without practice workflows
第一阶段 SHALL 只提供指南查看和导出，不提供文字作答、自动评分、顾问评分或语音模拟入口；旧 Interview 功能保持兼容但不得混入新指南合同。

#### Scenario: User opens a new interview guide
- **WHEN** 用户查看新生成的指南
- **THEN** 页面展示准备内容而不要求填写答案、提交评分或预约顾问
