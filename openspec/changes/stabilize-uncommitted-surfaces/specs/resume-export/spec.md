## Purpose

把简历版式做成数据库中的系统模板目录，生成版本时绑定模板并保存快照；HTML、DOCX 与可选 PDF 都按快照渲染。模板只决定版式，不得改写事实或削弱蓝图未达成标记。

## ADDED Requirements

### Requirement: Resume templates are catalog records
系统 SHALL 将简历版式存为模板目录记录，至少包含稳定标识、名称、版本号、状态，以及描述纸张、字体、颜色和布局的版式参数。本轮 MUST 提供一套系统默认模板（深蓝灰单页 ATS）。系统模板 MUST 不属于任何用户。个人简历 PDF、证件照和真实经历 MUST NOT 作为模板正文存储。

#### Scenario: Default system template exists after migration
- **WHEN** 空库升级到包含模板表的最新迁移
- **THEN** 存在一条可用的系统默认模板，且其版式参数足以驱动 HTML 与 DOCX 渲染

#### Scenario: Personal sample PDFs are not templates
- **WHEN** 系统枚举模板目录
- **THEN** 结果中不含任何真实个人简历文件或从私人样张复制的完整正文

### Requirement: Each resume version pins a template snapshot
生成或导出简历版本时，系统 MUST 记录所用模板标识，并保存当时的版式快照。之后修改模板目录 MUST 不改变已生成版本再次导出时的版式。未指定模板的存量版本 MUST 回落到系统默认模板并补写快照。

#### Scenario: Export uses the snapshot, not the live catalog
- **WHEN** 某版本生成时使用默认模板，随后系统默认模板的强调色被修改
- **THEN** 再次导出该版本仍使用生成时快照中的颜色

#### Scenario: Legacy version without a template still exports
- **WHEN** 导出一条尚未绑定模板的已有简历版本
- **THEN** 系统使用默认模板完成导出，并为该版本补写模板标识与快照

### Requirement: All export formats share one snapshot
同一版本的 HTML 预览、HTML 下载、DOCX 下载 MUST 使用同一份版式快照与同一份 `content_json`。PDF 导出若环境提供转换器则 MUST 使用同一快照；若转换器不可用，系统 MUST 返回明确错误，且 MUST 不因此阻断 HTML 与 DOCX。

#### Scenario: HTML and DOCX agree on sections and bullets
- **WHEN** 使用同一版本分别渲染 HTML 与 DOCX
- **THEN** 章节数、要点数和未达成标记出现次数一致

#### Scenario: PDF converter missing
- **WHEN** 用户请求 PDF 但运行环境没有可用转换器
- **THEN** 系统拒绝 PDF 并说明原因，该版本的 HTML 与 DOCX 仍可导出

### Requirement: Templates must not alter facts or achievement state
模板 MUST 只影响版式（纸张、页边距、字体、颜色、栏位、项目符号、分区顺序、可选照片槽）。模板 MUST NOT 增删经历内容、改写数字或工具、改变 `achieved`，也 MUST NOT 把蓝图条目变成已达成。可投递版本 MUST 仍只使用已确认事实。蓝图未达成要点 MUST 在 HTML、DOCX 和（若生成）PDF 中可见地标为未达成。

#### Scenario: Unachieved bullets remain visible
- **WHEN** 渲染一份含未达成学习目标的蓝图简历
- **THEN** 每个未达成要点都带可见的未达成标记，且仍引用对应学习目标

#### Scenario: Submittable export still fact-guarded
- **WHEN** 使用系统模板导出可投递版本
- **THEN** 导出内容仍只包含已确认事实，且不出现未达成学习目标冒充已完成经历

### Requirement: Optional portrait is user storage, not template data
模板可以声明可选证件照槽位。证件照 MUST 来自该用户的私有文件存储。模板记录 MUST NOT 内嵌证件照或私人样张。用户未提供照片时，系统 MUST 仍能按同一模板导出。

#### Scenario: Export without a portrait
- **WHEN** 版本绑定的模板支持照片槽但用户未上传证件照
- **THEN** 导出成功，版式中不出现他人照片或占位个人肖像文件
