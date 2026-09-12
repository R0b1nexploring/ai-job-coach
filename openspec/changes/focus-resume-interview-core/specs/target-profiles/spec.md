## Purpose

目标画像把用户提供的一份或多份 JD 转换成可追溯的岗位要求合同，为双轨简历、质量评审和面试指南提供唯一目标上下文，并防止 AI 添加输入中不存在的岗位要求。

## ADDED Requirements

### Requirement: Writing retains actual job context
系统 MUST 保留用户明确提供或从 JD 原文提取的岗位标题与公司，MUST NOT 用界面占位文案覆盖它们。缺失信息 SHALL 保持未知。生成快照 SHALL 保留 JD 原文以及要求的来源证据、频次、优先级；写作输入 MUST 包含真实岗位信息和必要原文上下文。

#### Scenario: Paste a JD containing a title and company
- **WHEN** 用户只粘贴包含公司与岗位名称的 JD
- **THEN** 保存岗位和创建画像后，写作输入包含原文提取的名称、要求证据和上下文，而不是“目标公司/目标岗位”占位值

#### Scenario: Job identity is absent from the source
- **WHEN** JD 未提供公司名称且用户未补充
- **THEN** 公司保持未知，系统不编造公司或将显示占位符存为真实值

### Requirement: Target profile supports exactly two source modes
系统 SHALL 支持 `single_jd` 和 `multi_jd` 两种目标画像模式，不提供脱离 JD 的自由想象模式。`single_jd` 必须绑定恰好一份 JD，`multi_jd` 必须绑定 2–10 份 JD。

#### Scenario: Create a single-JD profile
- **WHEN** 用户提交一份自己可访问的 JD 并选择 `single_jd`
- **THEN** 系统创建目标画像，并把该 JD 保存为唯一来源

#### Scenario: Reject an invalid multi-JD count
- **WHEN** 用户为 `multi_jd` 提交少于 2 份或多于 10 份 JD
- **THEN** 系统返回可理解的校验错误且不创建画像

### Requirement: Every target requirement is source-grounded
系统 MUST 为画像中的每项职责、硬性要求、加分项、关键词和工作条件保存稳定 requirement id、来源 JD 与逐字证据片段。证据不是对应 JD 原文子串的要求 MUST 被丢弃。

本要求约束来源与聚合结果，不要求创建画像时再次调用模型；系统 MAY 复用岗位保存时已有的结构化解析结果，但 MUST 对照对应 JD 快照重新验证证据。本轮不规定画像阶段的模型调用预算。

#### Scenario: Aggregate repeated requirements
- **WHEN** 多份 JD 都包含同一标准化能力要求
- **THEN** 系统合并该要求、记录出现频率，并保留每份来源 JD 的原文证据

#### Scenario: Remove an unsupported generated requirement
- **WHEN** 复用的结构化结果或模型输出中，有要求无法在任何输入 JD 中找到证据
- **THEN** 系统不保存该要求，并在不含 JD 正文的质量元数据中记录拒绝原因

### Requirement: Target profiles are private and reproducible
系统 SHALL 仅允许画像所有者访问画像及来源，并 SHALL 保存聚合快照和输入哈希，使既有简历包不因源 JD 后续编辑而改变。

#### Scenario: Another user requests a target profile
- **WHEN** 用户 B 请求用户 A 创建的目标画像
- **THEN** 系统返回 404 且不泄露来源 JD 或聚合内容

#### Scenario: A source JD changes after generation
- **WHEN** 目标画像已用于生成简历包后，其来源 Job 被修改
- **THEN** 既有简历包继续引用生成时的目标快照，新生成请求使用更新后的画像版本
