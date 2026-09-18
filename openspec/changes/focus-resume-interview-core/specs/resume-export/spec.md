> **当前范围（2026-09-18）**：完整业务路线按主计划顶部 R0–R6 与 tasks 第17节执行。恢复最小邀请试用、持久任务与真实文件验收；旧“上线暂缓”范围被覆盖，固定规模实验、原型库及完整编辑器仍延期。历史实现勾选不代表新增合同已验收。

> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

统一导出能力用一套版本化中文理工科模板生成可复现的 HTML、DOCX 和 PDF，并通过实际分页、字体和文本层检查确保单页视觉质量与 ATS 可读取性一致。

## ADDED Requirements

### Requirement: Local density selection is reproducible
本新三档模板要求继续作为后续改版规划；当前仅复用保存快照允许的间距调整并按下方真实交付要求验收。

新模板版本 SHALL 提供 `spacious/balanced/compact` 三档受限间距，通过固定 Chromium 与字体的实际布局测量选择可容纳正文的最宽松档位。系统 MUST 保存可复现的模板版本和选定配置，预览与 Chromium PDF 使用同一配置；字号、正文、锁定内容不得因选档改变。旧模板快照 MUST 保持原渲染行为，不补套未定义档位。运行时模型 MUST NOT 输出 HTML/CSS 或排版参数。

#### Scenario: Content needs a denser layout
- **WHEN** 正文在宽松档无法放入单页而在紧凑档可以
- **THEN** 本地选择通过测量与物理 QA 的档位，预览与导出同步，正文哈希及指南状态不变

#### Scenario: Content exceeds every allowed density
- **WHEN** 所有允许档位仍无法容纳正文
- **THEN** 系统返回可定位的溢出问题，遵循独立内容调整流程，不缩字号、不隐式删改正文

### Requirement: Visual quality is verified on rendered artifacts
下述固定12份案例规模属于后续模板发布实验；当前闭环必须验证真实截图与PDF质量，覆盖主计划输入类型但不恢复固定数量。

模板发布 SHALL 使用至少 12 份固定虚构正文覆盖短中长、长中英文、联系方式换行、多经历、技能与蓝图页脚，保存人工认可的截图基线。验收 MUST 检查层级、对齐、留白、完整显示及实际 PDF 物理质量，并记录实际转换器。备用转换器通过 MUST NOT 被记录为 Chromium 转换通过。

#### Scenario: PDF is technically valid but visually poor
- **WHEN** PDF 文本与字体检查通过，但存在不合理空白、标题日期错位或拥挤
- **THEN** 视觉验收仍不通过，调整本地模板后重新比较截图，不能只凭 HTTP 成功或页数合格勾选完成

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
系统 SHALL 仅由应用服务端或 worker 中的本地模板从同一已保存 content 和模板快照生成 HTML、DOCX 与 PDF。渲染、转换和重复下载 MUST NOT 调用模型；三种格式的章节顺序、可见 bullet、未达成标记和正文文本 MUST 一致。固定打印环境中的 HTML 打印预览与其生成的 PDF SHALL 使用相同布局；DOCX 在不同 Word 软件中的像素级排版一致性不属于交付要求。

#### Scenario: Download every supported format
- **WHEN** 用户下载同一版本的 HTML、DOCX 和 PDF
- **THEN** 三个产物包含相同章节和要点，且不泄露内部来源 id 或质量元数据

### Requirement: Rendering preserves saved copy
渲染器 MUST NOT 改写正文、截断句子或静默删除要点。所有格式 SHALL 读取同一已保存内容与模板快照；导出和重复下载 MUST NOT 隐式执行文案重生成或修改保存内容。单纯排版调整 MUST NOT 改变内容哈希。

#### Scenario: Download does not mutate a resume
- **WHEN** 用户导出或重复下载已有简历
- **THEN** 渲染前后的保存正文、锁定状态与内容哈希不变，不发起文案模型请求

### Requirement: Content overflow is resolved in the content workflow
确认正文容量导致超页时，系统 SHALL 先在保存的模板允许范围内调整间距，不缩小字号；未定义调整范围时 MUST 保持原值。仍超页时 MUST 返回实际页数及可定位的溢出内容，并拒绝超页 PDF。生成流程可将该问题交回内容阶段缩写相关未锁定要点；已有版本的下载请求 SHALL 只报告问题，由用户主动编辑或重生成，不得隐式改稿。内容调整 MUST 保留锁定要点的内容、位置和经历归属；无法容纳时保留原内容并说明原因。正文修改后 MUST 重新校验、保存内容哈希、使旧指南过期，再从新保存内容生成各格式；调整结果未通过内容门禁时 MUST NOT 覆盖原版本。

#### Scenario: Spacing adjustments cannot resolve overflow
- **WHEN** 模板允许的间距调整后仍超页
- **THEN** 系统返回溢出问题，渲染器不删改正文、不交付超页 PDF；需要缩写的文案交回内容阶段处理

#### Scenario: Locked content cannot fit on one page
- **WHEN** 容纳全部锁定内容将突破单页要求且调整间距无法解决
- **THEN** 系统保留原内容和锁定状态，说明无法生成合格单页 PDF，不擅自移动、缩写或删除锁定要点

#### Scenario: Copy changes to resolve overflow
- **WHEN** 内容阶段缩写未锁定文案并通过内容门禁
- **THEN** 系统保存新内容及哈希，使旧指南过期，所有格式从新内容渲染；单纯间距调整不改变内容哈希

### Requirement: Deliverable resumes pass physical PDF QA
正式交付的 PDF MUST 由本地 HTML 打印或本地 DOCX 转换生成，并为 A4 单页、无裁切、字体嵌入、具有 Unicode 文本映射且可提取全部可见章节和要点。系统 SHALL 以实际文件检查为准，不以估算行数替代验收。

#### Scenario: Estimated lines fit but the rendered PDF does not
- **WHEN** 字符数或估算行数符合预期，但实际 PDF 超页或裁切
- **THEN** 系统拒绝该 PDF 并诊断原因，确认正文容量溢出才进入内容调整流程；转换或排版技术故障仅进入本地导出修复，不能仅凭页数判定需要重写

### Requirement: PDF technical failures are isolated from copy generation
转换器缺失、转换异常以及字体嵌入、Unicode、裁切或文本丢失等技术故障 MUST 仅影响 PDF 任务，不得使已完成的简历版本失效，不得触发模型重写。系统 SHALL 保留已保存内容、哈希、指南状态及其他合格格式，允许本地修复依赖或转换后重试 PDF。转换器缺失 MUST 返回 `PDF_CONVERTER_UNAVAILABLE`，物理检查失败 MUST 返回 `PDF_QA_FAILED`；转换执行异常 SHALL 返回明确的独立导出失败原因。确认由正文容量导致的超页遵循独立的内容调整要求，不得与技术故障共用自动文案修复路径。

#### Scenario: No PDF converter is installed
- **WHEN** 环境既没有可用 Chromium 也没有 LibreOffice
- **THEN** HTML 与 DOCX 仍可导出，PDF 请求返回 `PDF_CONVERTER_UNAVAILABLE`，不重写简历

#### Scenario: PDF loses its Unicode mapping
- **WHEN** 本地转换成功但 PDF 缺少 Unicode 映射或丢失原本可见的文本
- **THEN** 系统拒绝该 PDF 并返回 `PDF_QA_FAILED`，只允许本地导出修复与重试，不请求缩写文案、不更新内容哈希或使指南过期

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

### Requirement: PDF exports are durable private artifacts
PDF SHALL 由独立持久任务读取已保存内容与模板快照生成，创建返回202，成功后提供鉴权下载。文件身份 MUST 绑定所有者、版本、内容哈希、模板快照哈希、格式及渲染器版本。并发相同导出 MUST 复用在途任务或有效产物；物理检查及私有上传都成功后才可记录可下载。下载或文件重建 MUST NOT 调用文案模型、修改简历或扣AI额度。

#### Scenario: Storage succeeds but database persistence fails
- **WHEN** 文件已上传但产物记录事务失败
- **THEN** 系统不宣布下载成功，重试保持幂等，孤儿文件进入延迟清理

#### Scenario: A previously generated file is missing
- **WHEN** 用户下载的有效记录对应对象已缺失
- **THEN** 系统允许重新排队该格式导出，不要求重生成简历或支付AI额度

### Requirement: Minimal content adjustment resolves overflow without a full editor
确认正文容量溢出且合法间距不能容纳时，界面 SHALL 提供简短“调整篇幅”动作，由用户主动触发异步内容调整。调整 MUST 保留锁定内容，重新校验并原子更新正文/语义哈希及指南过期状态；失败保留原版本。PDF技术故障 MUST 只提供导出重试，不触发改稿。此能力复用既有内容调整，不要求新增完整编辑器。

#### Scenario: Content reduction cannot preserve locked text
- **WHEN** 用户主动调整篇幅但保留锁定内容仍不能合格交付
- **THEN** 调整任务失败，原成稿及其他可用格式仍保留，不能静默删改锁定要点

### Requirement: Trial exports pass actual Chromium and viewport checks
邀请试用 SHALL 使用固定Chromium与中文字体生成两版PDF并完成单页A4、裁切、字体嵌入、Unicode与全文检查，同时验证HTML/DOCX/PDF正文、章节和蓝图标识一致。桌面及390px窄屏预览 MUST 完整显示页面；生产缺转换器不可跳过验收或将503算成功。首版无需恢复固定12份案例或新三档模板实验，现有快照允许的间距调整必须可复现。

#### Scenario: Local tests pass with another converter
- **WHEN** 本地LibreOffice转换成功但生产Chromium未验证
- **THEN** 记录本地通过与生产未验证，不能据此开放邀请或宣称Chromium路径成功
