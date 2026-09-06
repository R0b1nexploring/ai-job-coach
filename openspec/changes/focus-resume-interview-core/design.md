> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false`，在工作台、导出和指南标识待核验，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Context

现有主应用以 `Job + Match + ResumeVersion` 为中心，简历生成依赖单个岗位和已确认事实；`target/submittable`、逐条来源和 Fact Guard 已存在。经历库只覆盖实习/项目，面试记录同时承担题组、作答和顾问评分，主应用只导出 HTML/DOCX，而更完整的 PDF/QA 位于根目录旁路。新方向需要在保留旧数据与接口的前提下，把这些能力收敛为一个无需顾问介入的简历工作台。

约束包括：AI 文本不能成为已验证事实；未达成蓝图条目必须保持 `achieved:false` 且在渲染中可识别；真实简历、密钥和完整个人材料不得进入日志、测试夹具或 Git；外部 LLM 必须继续有本地安全回退。

## Goals / Non-Goals

**Goals:**

- 用一个目标画像统一单 JD 与多 JD 生成，并让每项要求可回溯到输入 JD。
- 用结构化素材和原子事实提高可改写空间，同时比现有整段文本 Guard 更精确。
- 一次异步生成同源双版本、自动质量报告和两份逐条指南。
- 将一套模板、三种导出和 PDF QA 合并进主应用，并复现历史版本。
- 保留旧数据、v1/v2 内容和旧接口，逐步把用户流量切到新工作台。

**Non-Goals:**

- 按年级、学历阶段或求职阶段建立不同流程。
- 多模板市场、自由排版、英文简历、实时语音或文字模拟面试。
- 继续完善校招看板、职位聚合、投递管理、顾问工作台、套餐或支付。
- 隐藏未达成状态、生成虚假经历，或以面试指南训练用户冒充未完成经历。

## Decisions

### 1. 所有生成都绑定 TargetProfile

新增 `target_profiles` 与 `target_profile_sources`。`mode=single_jd` 必须且只能关联一条当前用户可见的 Job；`mode=multi_jd` 必须关联 2–10 条。聚合结果保存为快照，要求项包含稳定 id、类别、优先级、出现频率以及每个来源的 `job_id + 原文片段`。服务端验证片段确实存在于对应 `raw_jd`，无来源的要求不得进入画像。

选择统一实体而不是为单 JD 保留独立生成路径，是为了让简历、质量报告和指南只维护一套合同。旧 Match 可作为单 JD 的辅助解释，但不再是创建双轨简历包的前置条件。

### 2. 复用并泛化 ExperienceEntry，ResumeFact 变为原子主张

不新增第二套素材表。扩展现有 `experience_entries`，使其用户侧名称为“简历素材”，`kind` 支持 education、internship、employment、project、research、competition、award、certificate、skill；新增 `details_json`、`clarifications_json`、`completeness_score` 和 draft/confirmed 状态。

`details_json` 统一保存背景、目标、个人职责、动作、工具、困难、取舍、结果、指标、团队边界和核验材料。上传解析或用户表单先创建素材，AI 只生成尚缺字段的追问。确认时服务端将素材拆为多个 `ResumeFact`，并为事实增加 `material_id`、`claim_type` 与 `evidence_json`；每个事实只表达一个可确认主张。旧 `linked_fact_id` 和旧事实继续读取，但新路径不再依赖一条素材只能映射一个事实。

选择扩展现有表而非迁移到全新材料表，是为了保留 `0008` 数据和隐私清理逻辑；用户隔离、范本不可直接确认及原始来源规则保持不变。

### 3. ResumeBundle 是双轨交付与异步状态边界

新增 `resume_bundles`，保存用户、基础简历、目标画像、事实快照、目标快照、模板快照、状态和生成元数据。每个 bundle 必须恰好有一条 `kind=submittable` 和一条 `kind=target` 的 ResumeVersion；ResumeVersion 新增 `bundle_id`、`target_profile_id`、`quality_report_json`、`content_hash` 和 `template_snapshot_json`，并允许多 JD 版本的旧 `job_id` 为空。

创建接口返回 `202` 与 bundle 状态。使用数据库中的 queued/generating/ready/degraded/failed 状态和带 claim token 的生成运行记录，进程内 worker 在本地运行，不引入 Redis/Celery；重复请求由幂等键和请求哈希复用同一 bundle。进程中断后的 generating 任务可由维护任务重新排队。

### 4. content_version=3 保留旧 kind，但强化逐条合同

继续使用 `submittable/target`，避免破坏旧消费者。v3 每个 bullet 包含稳定 `id`、`text`、`source_fact_ids`、`source_target_ids`、`requirement_ids`、`achieved`、`locked` 和空的 `new_claims`。真实版只能引用已确认事实；蓝图的未来项必须引用当前画像要求和未达成目标。

生成顺序为：证据矩阵规划 → 两版写作 → 确定性 Fact Guard → 结构化质量评审 → 按问题摘要最多修复两轮 → 版面预算。Fact Guard 对真实性拥有最终裁决权，LLM critic 不能放行无来源主张。失败后生成确定性真实版并将 bundle 标为 degraded；无法溯源的蓝图项直接省略。

局部重生成按 bullet/section/all 三种 scope 工作，locked bullet 不被全局重生成覆盖。任何用户编辑或重生成都会更新内容哈希、重新执行门禁，并把绑定旧哈希的指南标为 stale。

### 5. 质量分为硬门禁与解释性评分

硬门禁包括零无来源主张、kind/achieved 语义、目标要求覆盖、单页预算、导出内容一致和可解析文本层。解释性评分覆盖目标相关性、具体性、个人贡献、信息密度、可读性、ATS 和面试可辩护性，保存分项分数、问题和修复历史。

只有硬门禁全部通过的版本进入 ready；安全确定性回退进入 degraded 并显示明确提示。解释性评分用于排序修复问题，不允许为了提高分数放松 Fact Guard。

### 6. 一份版本化模板快照，不建模板目录

首版模板配置固定为 `classic-navy-ats-v2`，由应用内版本化 JSON 提供，并在 bundle/version 上保存快照。当前只有一套模板，因此不创建 `resume_templates` 表或模板后台；以后增加第二套模板时再引入目录。

分区顺序固定为求职方向、教育、实习/工作、项目/科研/竞赛、奖项证书、技能。蓝图未来项在正文附上轻量上标 `*`，页脚统一解释；真实版无标记。HTML 是打印预览与 PDF 的规范布局，DOCX 从同一内容和 profile 生成。PDF 优先由 headless Chromium 打印 HTML；不可用时可由 LibreOffice 转换 DOCX，但仍须通过页数、字体、文本层和内容计数 QA。两者都不可用时 HTML/DOCX 可用，PDF 返回明确依赖错误。

### 7. InterviewGuide 与旧 Interview 分离

新增 `interview_guides`，绑定 `resume_version_id`、`target_profile_id`、版本内容哈希、guide kind、内容和质量报告。bundle ready 后为两个版本排队生成指南；真实版覆盖每个可见 bullet 的主问、连续追问、六段式讲法、个人边界、核验材料和危险说法，并补充 60/90 秒自介、JD 题、反问和检查表。蓝图版只为未来项生成风险卡、当前诚实边界和补证要求，不生成冒充完成的答案。

每张卡引用 bullet id 及其事实/目标来源，服务端要求可见 bullet 覆盖率为 100%。旧 Interview、答题和顾问评分接口保留，只从新导航移除。

### 8. 新工作台渐进接管用户入口

新增 `/app/resume-studio`，以目标、素材、双版本、导出、指南五个连续区域组织流程；允许上传或空白建档、逐条查看来源、锁定、重生成、排序、撤销和版本对比。普通用户主导航只保留工作台、指南和账户设置；旧 URL、API 和管理角色页面继续可访问，避免破坏已有演示与数据。

自助预览和导出只要求 Guard 与质量硬门禁通过，不要求顾问批准。旧投递队列若继续使用 ResumeVersion，仍可保留其原有审核要求，不反向阻塞新工作台导出。

### 9. 规格优先级通过新增裁决而非改写历史

在 `PROJECT_SPEC.md` 新增方向裁决章节，并新增 `docs/plan-resume-interview-core.md`。`AGENTS.md` 将新计划置于旧 `plan-target-resume-loop.md` 之前；旧文档保留为历史实施记录。`stabilize-uncommitted-surfaces` 保留但标为暂停，不执行其校招和模板目录任务。

## Risks / Trade-offs

- [多轮生成显著增加延迟和模型成本] → 异步 bundle、最多两轮修复、内容哈希缓存和显式 degraded 状态控制成本。
- [四类理工科质量差异大] → 使用共享结构合同加四类独立虚构基准；未通过某类基准时不得宣称该类达到高质量。
- [原子化事实增加填写负担] → 先解析/预填，再只追问影响表达质量的缺口，允许保存草稿。
- [单页目标与信息完整性冲突] → 简历保持单页，蓝图目标说明和详细质量报告作为独立附件，不挤入正文。
- [PDF 在不同机器上字体与分页波动] → 快照保存布局参数，部署安装固定字体与 Chromium，并以实际 PDF QA 作为发布门禁。
- [旧流程与新工作台长期并存] → 新接口只做兼容读取，导航和验收只围绕新主流程；后续独立 change 再移除旧能力。
- [页脚标记可能被用户删除] → 系统导出的蓝图始终重新渲染标记；用户修改外部文件不被系统认证为真实版本。

## Migration Plan

1. 先修复当前前端构建并提交仓库忽略边界，建立可靠基线。
2. `0009_add_target_profiles_and_material_claims` 新增目标画像/来源并扩展素材与原子事实；回填旧 ExperienceEntry 状态与旧事实兼容字段。
3. `0010_add_resume_bundles_and_interview_guides` 新增 bundle、运行记录和指南，并扩展 ResumeVersion；旧版本保持原值，不强制回填 bundle。
4. 上线新 API 和工作台但保留旧入口；虚构种子数据同时覆盖单 JD、多 JD 和四类专业。
5. 完成质量与导出门禁后将普通用户默认入口切到工作台，并隐藏非核心导航。
6. 回滚时先恢复旧导航，再降级 `0010` 和 `0009`；旧 Job、Resume、ResumeFact、ResumeVersion 与 Interview 数据保持可读。
