> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false`，在工作台、导出和指南标识待核验，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

双轨生成能力从同一目标画像和真实事实快照自动交付一份可直接投递的真实能力简历与一份目标蓝图 Plus，并让两者的事实状态、差距和演进关系始终清晰可核验。

## ADDED Requirements

### Requirement: One request creates one paired resume bundle
系统 SHALL 对每个成功生成请求创建一个 ResumeBundle，并在同一快照下生成恰好一份 `submittable` 和一份 `target` ResumeVersion。重复的幂等请求 MUST 返回同一 bundle。

#### Scenario: Generate from a single target profile
- **WHEN** 用户用已确认素材和有效目标画像创建简历包
- **THEN** 系统异步生成同源双版本，并可通过 bundle 查询各自状态与 id

#### Scenario: Replay the same request
- **WHEN** 客户端使用相同幂等键和相同请求内容重试
- **THEN** 系统不重复扣减资源或调用模型，并返回原简历包

### Requirement: Studio resumes allow AI expansion
新生成的工作台 v3 简历 SHALL 允许补充原事实中不存在的主张。系统 MUST 将此类条目标识为 AI 待核验，MUST NOT 自动写成用户已确认事实。缺少事实支持 SHALL 仅产生提示，不阻止预览和导出。

#### Scenario: Model adds a metric
- **WHEN** 模型补充原素材中没有的量化成果，且来源归属和版面检查通过
- **THEN** 系统保留该要点及新增主张，标识 AI 待核验，并允许生成、预览和导出

#### Scenario: Generate without confirmed facts
- **WHEN** 用户已绑定有效目标画像但尚无已确认素材
- **THEN** 系统允许生成带待核验标识的双轨草稿

#### Scenario: Reference another user's fact
- **WHEN** 模型引用不属于当前生成上下文的事实 ID
- **THEN** 来源归属门禁拒绝该引用，不因允许扩写而放行

### Requirement: Blueprint Plus represents future target content visibly
蓝图 Plus SHALL 同时包含适用的真实事实和未达成目标。每个未来要点 MUST 引用目标 requirement、保持 `achieved:false` 并在正文显示轻量 `*`；渲染页脚 MUST 解释该标记表示尚未形成可核验经历。

#### Scenario: Render a future certificate target
- **WHEN** 蓝图包含尚未取得且有目标要求依据的证书目标
- **THEN** 该要点携带目标来源、显示 `*`，且不会出现在真实能力简历中

#### Scenario: Confirm a previously unachieved target
- **WHEN** 用户补充证据并确认蓝图目标已经真实完成
- **THEN** 系统把对应内容转为已确认事实，并允许下一次真实能力简历无标记地使用它

### Requirement: Generation performs bounded automatic repair
系统 SHALL 按“规划、写作、事实校验、质量评审、定向修复、排版 QA”执行生成，质量失败时最多进行两轮修复。无法达到高质量但能产生安全确定性结果时 MUST 标为 `degraded`，不得静默显示为 ready。

#### Scenario: Quality improves after one repair
- **WHEN** 首稿事实合规但存在重复或岗位相关性不足
- **THEN** 系统携带问题摘要重写受影响内容，并在质量报告中记录修复历史

#### Scenario: External model remains unavailable
- **WHEN** 外部模型重试后仍不可用
- **THEN** 系统返回事实合规的本地基础版本、标记 degraded，并明确告知用户质量降级

### Requirement: Users can edit and selectively regenerate
用户 SHALL 能按 bullet、section 或整份简历重生成，锁定的 bullet MUST 在全局重生成中保持不变。任何编辑或重生成 MUST 重跑事实和质量门禁，并使旧内容哈希对应的指南过期。

#### Scenario: Regenerate one unlocked bullet
- **WHEN** 用户只重生成一个未锁定要点
- **THEN** 系统仅替换该要点、保留其余内容，并重新计算版本质量与哈希

