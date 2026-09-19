> **当前范围（2026-09-18）**：完整业务路线按主计划顶部 R0–R6 与 tasks 第17节执行。恢复最小邀请试用、持久任务与真实文件验收；旧“上线暂缓”范围被覆盖，固定规模实验、原型库及完整编辑器仍延期。历史实现勾选不代表新增合同已验收。

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

### Requirement: JD persistence precedes asynchronous analysis
单JD主操作 SHALL 先保存原文并获取独立岗位ID，再创建画像分析任务；新流程保存JD不得等待模型分析。系统 MUST 保留原文与job_ids的类型边界，支持1份或2–10份有效来源，失败后可复用已保存来源重试。任务冻结对应输入revision，后续源编辑不得改变进行中的分析。

#### Scenario: Analysis fails after JD storage succeeds
- **WHEN** 岗位原文已保存但模型分析失败或页面断网
- **THEN** 用户可基于同一已保存岗位重试，不重复创建岗位，不把原文拼入job_ids

### Requirement: Strategy advice does not invent target requirements
岗位写作策略 SHALL 引用画像中已有要求及其证据。通用岗位经验 MUST 标记为内部建议，不能写回画像成为该雇主硬条件。多JD SHALL 保留逐JD依据，以有证据的共同或互补要求形成一致目标；显式互斥且无法一致时提示拆分并保留已存JD，分类不确定或模型评分低不能单独拒绝。

#### Scenario: Strategy infers a useful practice absent from the JD
- **WHEN** 策略建议讨论测试或设计取舍但JD没有明确要求
- **THEN** 系统将其作为写作建议，不添加虚构JD证据、频次或招聘门槛

#### Scenario: Multiple jobs have incompatible explicit targets
- **WHEN** JD明确职责或条件互斥，无法形成一致的目标叙事
- **THEN** 系统提示用户分开生成，保留来源，不拼接为不存在的职位，也不捏造候选人同时具备所有条件
