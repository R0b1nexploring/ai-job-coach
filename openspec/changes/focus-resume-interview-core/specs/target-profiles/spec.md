## Purpose

目标画像把用户提供的一份或多份 JD 转换成可追溯的岗位要求合同，为双轨简历、质量评审和面试指南提供唯一目标上下文，并防止 AI 添加输入中不存在的岗位要求。

## ADDED Requirements

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

#### Scenario: Aggregate repeated requirements
- **WHEN** 多份 JD 都包含同一标准化能力要求
- **THEN** 系统合并该要求、记录出现频率，并保留每份来源 JD 的原文证据

#### Scenario: Remove an unsupported generated requirement
- **WHEN** AI 返回的画像要求无法在任何输入 JD 中找到证据
- **THEN** 系统不保存该要求，并在不含 JD 正文的质量元数据中记录拒绝原因

### Requirement: Target profiles are private and reproducible
系统 SHALL 仅允许画像所有者访问画像及来源，并 SHALL 保存聚合快照和输入哈希，使既有简历包不因源 JD 后续编辑而改变。

#### Scenario: Another user requests a target profile
- **WHEN** 用户 B 请求用户 A 创建的目标画像
- **THEN** 系统返回 404 且不泄露来源 JD 或聚合内容

#### Scenario: A source JD changes after generation
- **WHEN** 目标画像已用于生成简历包后，其来源 Job 被修改
- **THEN** 既有简历包继续引用生成时的目标快照，新生成请求使用更新后的画像版本

