## Purpose

统一简历素材能力让有旧简历和从空白开始的用户都能以结构化方式沉淀真实教育、经历、项目与资质，并通过针对性追问形成足以支撑高质量改写的原子事实。

## ADDED Requirements

### Requirement: Project archetypes are independently sourced references
本原型库实验在 2026-09-12 本轮暂缓，不是蓝图 STAR 项目生成的前置依赖；本轮直接使用现有目标画像与可选素材。

项目原型实验 SHALL 使用 12–24 条版本化本地原型，包含岗位方向、问题、任务步骤、工具、产物、指标槽位、核验材料、表达示例和来源说明。检索结果 MUST 与用户素材和事实分开记录，并保存命中内容及版本；原型 ID MUST NOT 用作用户事实 ID。衍生扩写 SHALL 保留既有 AI 来源与未达成状态。数据库化、大规模收集和向量检索 SHALL 延后到对照实验确认收益后另行规划。

#### Scenario: A relevant archetype is retrieved
- **WHEN** 实验链路为某段经历选中相关原型
- **THEN** 写作使用其技术步骤和表达范式作为参考，最多选入 2 条，不将示例公司、日期、指标或成果自动确认为用户事实

#### Scenario: Archetypes do not improve writing
- **WHEN** 加入原型的对照组未显示明确质量或编辑量收益
- **THEN** 默认链路保留简报与用户素材选材，记录实验结论，不以扩大数据库替代质量验证

### Requirement: Users can build materials from upload or blank state
系统 SHALL 支持从 DOCX、文本型 PDF 解析素材，也 SHALL 允许用户不上传文件直接建立素材库。素材类型 MUST 覆盖教育、实习、工作、项目、科研、竞赛、奖项、证书和技能，且流程不得按年级分叉。

#### Scenario: Start without an existing resume
- **WHEN** 用户选择从空白开始并新增一条项目素材
- **THEN** 系统创建用户私有草稿素材，不要求先上传原始简历

#### Scenario: Parse an existing resume
- **WHEN** 用户上传受支持的简历文件
- **THEN** 系统预填可追溯到原文的素材，未知字段保持为空

### Requirement: Material cards capture evidence-rich details
每条素材 SHALL 支持背景、目标、个人职责、动作、工具、困难、取舍、结果、指标、团队边界和核验材料。AI MUST 只针对缺失或含糊字段提出问题，不得替用户填写未知事实。

#### Scenario: Ask a targeted ownership question
- **WHEN** 项目素材记录了团队结果但没有个人职责边界
- **THEN** 系统生成关于本人具体贡献的追问，并保持该素材未确认

#### Scenario: Preserve an unknown metric
- **WHEN** 用户没有提供项目指标或量化结果
- **THEN** 系统允许指标为空且不生成猜测数字

### Requirement: Confirmed materials become atomic facts
素材确认时，系统 MUST 将其拆分为单一主张的原子事实，并为每项事实保存素材关联、主张类型、来源和核验信息。未确认素材 MUST NOT 作为已确认事实使用，但 SHALL 允许作为 v3 `ai_expansion` 求职版与蓝图的文案参考；没有已确认素材不得阻止草稿生成。生成文案 MUST NOT 自动确认素材或回写已确认事实库，AI 补充保持 `verification_status=ai_generated`、`achieved:false`。素材采集不猜填未知事实与简历文案允许扩写是不同阶段的约束。

#### Scenario: Generate copy from unconfirmed material
- **WHEN** 用户保存草稿素材但未确认，并基于有效目标画像生成双版本
- **THEN** 系统允许使用草稿作为参考，保留其未确认来源状态，新增文案保留 AI 来源状态，不创建已确认事实

#### Scenario: Confirm a complete internship
- **WHEN** 用户确认一条包含真实组织、个人动作和结果的实习素材
- **THEN** 系统创建分别表达角色、动作、工具和结果的原子事实，并全部关联回该素材

#### Scenario: Reject unsupported credential ownership
- **WHEN** 用户尝试确认仅来自范例且没有本人核验信息的奖项或证书
- **THEN** 系统拒绝确认并说明需要的真实证据

### Requirement: Material ownership and edits remain isolated
系统 MUST 隔离不同用户的素材和事实。已确认素材被编辑后，受影响事实 MUST 回到待确认状态，引用这些事实的简历质量状态与指南 MUST 被标记为过期。

#### Scenario: Edit a confirmed result
- **WHEN** 用户修改已经进入简历的项目结果
- **THEN** 系统取消受影响事实的确认，并使相关简历包等待重新校验

#### Scenario: Access another user's material
- **WHEN** 用户请求更新或确认不属于自己的素材
- **THEN** 系统返回 404 且不修改任何事实
