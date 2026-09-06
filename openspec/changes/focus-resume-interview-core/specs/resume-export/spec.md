> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false`，在工作台、导出和指南标识待核验，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

统一导出能力用一套版本化中文理工科模板生成可复现的 HTML、DOCX 和 PDF，并通过实际分页、字体和文本层检查确保单页视觉质量与 ATS 可读取性一致。

## ADDED Requirements

### Requirement: A single versioned template drives every format
系统 SHALL 使用 `classic-navy-ats-v2` 作为首版唯一模板，并在生成时把模板配置快照保存到版本。历史版本再次导出 MUST 使用原快照，不受之后模板更新影响。

#### Scenario: Template changes after a version is created
- **WHEN** 系统默认模板颜色或间距更新后再次导出旧版本
- **THEN** 旧版本继续使用创建时的模板快照

### Requirement: Resume section order is fixed and empty sections disappear
模板 MUST 按“姓名与求职方向、教育背景、实习/工作、项目/科研/竞赛、奖项证书、技能”排序，空分区 MUST 隐藏。教育背景 MUST 紧接求职方向之后。

#### Scenario: Resume contains education and projects
- **WHEN** 系统渲染同时含教育和项目的版本
- **THEN** 教育背景出现在求职方向之后且早于项目分区

### Requirement: HTML DOCX and PDF preserve the same resume content
系统 SHALL 从同一 content 和模板快照生成 HTML、DOCX 与 PDF。三种格式的章节、可见 bullet、未达成标记和正文文本 MUST 一致。

#### Scenario: Download every supported format
- **WHEN** 用户下载同一版本的 HTML、DOCX 和 PDF
- **THEN** 三个产物包含相同章节和要点，且不泄露内部来源 id 或质量元数据

### Requirement: Deliverable resumes pass physical PDF QA
正式交付的 PDF MUST 为 A4 单页、无裁切、字体嵌入、具有 Unicode 文本映射并可提取全部可见章节和要点。若 PDF 转换器不可用，系统 SHALL 保留 HTML/DOCX，并返回明确的 PDF 依赖错误。

#### Scenario: PDF exceeds one page
- **WHEN** 转换后的 PDF 页数不是一页
- **THEN** 系统不交付该 PDF，并将分页问题返回生成修复流程

#### Scenario: No PDF converter is installed
- **WHEN** 环境既没有可用 Chromium 也没有 LibreOffice
- **THEN** HTML 与 DOCX 仍可导出，PDF 请求返回明确的服务不可用错误

### Requirement: Blueprint status remains visible but unobtrusive
蓝图未来要点 SHALL 以轻量上标 `*` 标识，并在页脚统一说明“`*` 为目标蓝图内容，尚未形成可核验经历”。真实能力版 MUST NOT 显示该说明。

#### Scenario: Export a mixed blueprint
- **WHEN** 蓝图同时包含已确认事实和未达成目标
- **THEN** 只有未达成要点显示 `*`，页脚恰好出现一次说明

### Requirement: Optional portrait does not define a second template
系统 SHALL 默认生成无照片版本，并允许用户提供私有证件照作为同一模板的可选输入。照片不得进入日志、模板快照或测试夹具，有无照片均 MUST 通过单页 QA。

#### Scenario: Export without a portrait
- **WHEN** 用户未上传证件照
- **THEN** 模板自动回收照片区域且保持单页布局

