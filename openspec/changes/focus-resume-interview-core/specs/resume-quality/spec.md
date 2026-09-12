> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

简历质量能力区分本地内容硬门禁、解释性评审与实际文件检查；AI 扩写可以交付但不得被系统升级为已确认事实。

## ADDED Requirements

### Requirement: STAR quality checks substance and causal consistency
系统 MUST 检查蓝图项目 STAR 信息及其在可见正文中的覆盖，并 SHALL 提供项目级的具体性、个人贡献、行动与结果因果关系、技术合理性和可验证性评审。字段非空或包含 S/T/A/R 关键词 MUST NOT 被当作质量证明。错误 SHALL 定位到具体项目和要点；缺少必需元素、错误来源或目标成果误标实测按内容错误处理，低分和风格建议不单独触发自动重写。

#### Scenario: Four fields contain vague filler
- **WHEN** 项目四个字段分别只有“业务需要、负责开发、使用工具、效果良好”
- **THEN** 评审指出缺少具体问题、个人目标、行动和验证依据，不能仅因四字段非空而宣称 STAR 质量优秀

#### Scenario: Actions cannot support the claimed result
- **WHEN** 项目行动仅描述制作界面，结果却宣称完成生产系统性能优化
- **THEN** 评审定位行动与结果脱节并给出具体问题，不因存在数字而给出高质量结论

### Requirement: Critical quality gates are deterministic
系统 MUST 在本地组装阶段检查来源 ID 与经历归属、结构、kind/achieved 语义及目标覆盖，在实际渲染后独立检查文件质量。字符数或估算行数 SHALL 仅作排版预判，MUST NOT 代替实际文件检查。`ai_expansion` 文案的事实不足只能形成内部状态或质量提示，不得被写成用户已确认事实。LLM 评分 MUST NOT 覆盖或放宽任何硬门禁。

#### Scenario: A critic approves an invalid reference
- **WHEN** LLM critic 给出高分但本地检查发现来源 ID 不存在、不属于当前上下文或与所归属经历不一致
- **THEN** 内容门禁仍拒绝该结果，不因模型评分高而放行

#### Scenario: AI expansion lacks factual support
- **WHEN** v3 文案包含没有事实支持的新增主张，但没有非法引用且其他内容门禁通过
- **THEN** 系统保留 AI 扩写状态并允许继续渲染，不将新增主张写入用户已确认事实

### Requirement: Model review is explanatory
系统 SHALL 为两版简历保存可解释的质量评审结果。模型评审仅用于补充目标相关性、表达与可辩护性建议；模型不可用时系统 MUST 明确标注使用确定性检查，且不得把确定性结果表示为模型评分。

首次双版本生成和后续重生成 MUST 均执行模型评审，问题 SHALL 绑定受影响 bullet 并给出可操作建议。缺失的评分维度 MUST 显示未评估，不得用固定分数补成模型评分；确定性报告 SHALL 展示检查依据，不能用有数字、要点多等浅层规则证明专业质量。

#### Scenario: First draft passes structural checks
- **WHEN** 初次双版本通过本地内容门禁
- **THEN** 两版均获得真实模型评审或明确的评审降级结果，不能仅凭确定性硬门禁宣布文案质量验收完成

#### Scenario: Critic omits a dimension
- **WHEN** 模型评审没有返回某维度
- **THEN** 该维度显示未评估，不以常量或确定性估分冒充模型评分

#### Scenario: Critic reports weak wording without gate failures
- **WHEN** 内容硬门禁通过，但 critic 给出低分或表达重复、相关性不足的建议
- **THEN** 系统保存解释性建议，不仅因该评分自动重写或判定内容 failed

#### Scenario: Critic is unavailable
- **WHEN** 文案已通过确定性硬门禁但模型质量评审不可用
- **THEN** 系统保存确定性质量报告，简历标为 degraded 并说明评审降级来源，不把确定性评分冒充模型评分

### Requirement: Quality reports are actionable and versioned
每个简历版本 SHALL 保存目标相关性、具体性、个人贡献、信息密度、可读性、ATS 和面试可辩护性分项，以及问题、修复历史、评审版本和内容哈希。

#### Scenario: User opens a quality report
- **WHEN** 用户查看 ready 或 degraded 版本
- **THEN** 系统展示每个维度的结果、影响要点和可执行改进建议，不显示完整模型 prompt

### Requirement: High-priority requirements cannot disappear silently
目标画像中的高优先级要求 MUST 在求职版中有事实证据，或在蓝图 Plus 中有未达成目标。求职版的 AI 扩写不得计为已经具备该能力的事实证据。系统 MUST 在质量报告中列出未覆盖要求。

#### Scenario: No fact supports a must-have requirement
- **WHEN** 真实素材无法支持一项高优先级要求
- **THEN** 求职版允许保留 AI 扩写建议但不得计为已确认能力，蓝图以未达成目标覆盖该要求，并在质量报告中说明差距

### Requirement: Degraded outputs remain transparent
最终简历内容 MUST 通过内容门禁才能进入 ready 或 degraded。工作台 MUST 说明文案或评审的降级来源，提示不得写入简历正文。每种格式 MUST 独立通过对应文件门禁才可交付；PDF 失败不得使已通过内容门禁的版本失效。最终内容门禁不通过时 MUST 标为 failed，不得以 degraded 交付。

#### Scenario: Safe local fallback passes hard gates
- **WHEN** 本地回退内容通过内容门禁
- **THEN** 简历状态保持 degraded，工作台说明回退来源，并允许预览及下载已通过文件门禁的格式

#### Scenario: Layout gate fails
- **WHEN** 最终 PDF 超页或文本被裁切
- **THEN** 系统阻止该格式交付并返回具体 QA 问题，保留已完成的简历内容与其他可用格式；按导出规格诊断正文容量溢出或技术故障，只有前者进入独立内容调整流程，下载请求本身不改稿

### Requirement: Supported STEM quality is benchmarked
本要求及下方对照实验保留为后续规划；2026-09-12 本轮不执行固定案例数量、盲评评分阈值或发布放行条件，相关内容回归仍保留。

发布 SHALL 使用完全虚构数据覆盖机械制造、电子自动化、计算机数据、化学材料与生物医药四类基准。真实授权材料只可进行本地一次性人工验收，不得进入仓库、日志或固定测试。

#### Scenario: Release quality is evaluated
- **WHEN** 准备发布新的生成策略或模板版本
- **THEN** 四类自动基准全部通过，且人工盲评在岗位相关性、清晰度、个人贡献、专业可信度和可辩护性上各方向平均不低于 4/5

### Requirement: Writing improvements have comparative evidence
本要求为后续实验，不是本轮 STAR 与指南实施的前置任务。

文案实验 MUST 至少使用 12 个完全虚构案例，覆盖机械制造、电子自动化、计算机数据、化学材料与生物医药（合并为第四方向），每方向包含丰富、稀疏、空白素材。系统 SHALL 对比当前生成、简报选材、简报选材加原型三组，固定模型与参数、每例重复 3 次并盲评。报告 MUST 记录五项评分、重复表达、错误经历归属、扩写误标事实、人工修改量及耗时；有用量信息时记录 token，不为本实验新增生产统计系统。回退样例和协议替身测试 MUST NOT 代替真实文案验收。

#### Scenario: Decide whether to adopt archetype retrieval
- **WHEN** 三组实验完成
- **THEN** 以各方向各维度平均至少 4/5 为发布质量门槛，结合原型组相对简报组的评分、修改量和成本作出书面采用或暂缓结论；归属错误和扩写误标事实必须为零
