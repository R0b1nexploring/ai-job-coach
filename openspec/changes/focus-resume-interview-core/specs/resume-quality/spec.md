> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false`，在工作台、导出和指南标识待核验，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

简历质量能力把“好简历”落实为不可绕过的事实与版面硬门禁，以及可解释、可修复的岗位相关性和表达评分，使自动交付既有竞争力又不会牺牲真实性。

## ADDED Requirements

### Requirement: Critical quality gates are deterministic
系统 MUST 以确定性规则校验来源完整、kind/achieved 语义、目标覆盖、内容预算、导出一致性和 ATS 文本可读性。LLM 评分 MUST NOT 覆盖或放宽任何硬门禁。

#### Scenario: A critic approves an unsupported claim
- **WHEN** LLM critic 给出高分但 Fact Guard 发现无来源主张
- **THEN** 版本仍被阻止进入 ready，且问题归入事实完整性门禁

### Requirement: Quality reports are actionable and versioned
每个简历版本 SHALL 保存目标相关性、具体性、个人贡献、信息密度、可读性、ATS 和面试可辩护性分项，以及问题、修复历史、评审版本和内容哈希。

#### Scenario: User opens a quality report
- **WHEN** 用户查看 ready 或 degraded 版本
- **THEN** 系统展示每个维度的结果、影响要点和可执行改进建议，不显示完整模型 prompt

### Requirement: High-priority requirements cannot disappear silently
目标画像中的高优先级要求 MUST 在真实能力版中有事实证据，或在蓝图 Plus 中有未达成目标。系统 MUST 在质量报告中列出未覆盖要求。

#### Scenario: No fact supports a must-have requirement
- **WHEN** 真实素材无法支持一项高优先级要求
- **THEN** 真实版不编造该能力，蓝图以未达成目标覆盖它，并在两版质量报告中说明差距

### Requirement: Degraded outputs remain transparent
仅当事实与版面硬门禁通过时，degraded 版本才可预览和导出；工作台 MUST 显著提示这是基础降级版本，但提示不得写入真实简历正文。硬门禁未通过的版本不得导出。

#### Scenario: Safe local fallback passes hard gates
- **WHEN** 本地回退内容可追溯且排版合格，但解释性质量未达 ready 标准
- **THEN** 用户可带工作台警告预览和导出，版本状态保持 degraded

#### Scenario: Layout gate fails
- **WHEN** 最终 PDF 超页或文本被裁切
- **THEN** 系统阻止该格式交付并返回具体 QA 问题

### Requirement: Supported STEM quality is benchmarked
发布 SHALL 使用完全虚构数据覆盖机械制造、电子自动化、计算机数据、化学材料与生物医药四类基准。真实授权材料只可进行本地一次性人工验收，不得进入仓库、日志或固定测试。

#### Scenario: Release quality is evaluated
- **WHEN** 准备发布新的生成策略或模板版本
- **THEN** 四类自动基准全部通过，且人工盲评在岗位相关性、清晰度、个人贡献、专业可信度和可辩护性上各方向平均不低于 4/5

