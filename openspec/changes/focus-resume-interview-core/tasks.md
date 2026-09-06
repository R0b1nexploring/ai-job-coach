## 1. 基线、仓库卫生与优先级裁决

- [x] 1.1 修复 `apps/web` 当前构建，使 `npm run build` 成功且不引入新的 TypeScript 错误
- [x] 1.2 核对 `.gitignore` 覆盖 `tmp/`、`output/`、`resume_pdf/resume_self/`、`resume_pdf/private/`、`var/`、`data/jd_collection.json`、`data/job_intelligence_analysis.md` 与 `scripts/fetch_job_jds.py`，并用 `git status` / `git check-ignore` 确认不列出个人 PDF 或渠道原始导入
- [x] 1.3 新增 `docs/plan-resume-interview-core.md`，写明目标画像、素材确认、双轨生成、导出和面试指南的实施顺序；人工对照本 change 的 proposal 无矛盾
- [x] 1.4 在 `PROJECT_SPEC.md` 新增方向裁决章节，记录本 change 优先于旧全流程计划，并保留既有 §27 为历史记录
- [x] 1.5 更新 `AGENTS.md`：把 `docs/plan-resume-interview-core.md` 置于 `docs/plan-target-resume-loop.md` 之前，读回确认冲突裁决顺序正确
- [x] 1.6 保持 `stabilize-uncommitted-surfaces` 暂停，不执行其校招简章、`resume_templates` 目录表和渠道任务；打开其 proposal 顶部暂停说明即可确认

## 2. 目标画像数据模型与 API

- [x] 2.1 新增 `TargetProfile` 与 `TargetProfileSource`，保存 `single_jd` / `multi_jd`、聚合快照、输入哈希，以及每项要求的稳定 id、类别、优先级、出现频率和 `job_id + 原文片段`。用模型导入或单元测试确认可实例化
- [x] 2.2 在 Alembic `0009_add_target_profiles_and_material_claims` 中建立上述表（可与 3.1 同一迁移）。空库执行 `alembic upgrade head` 且 `test_migrations.py` 通过
- [x] 2.3 实现创建/读取 API：`single_jd` 恰好绑定 1 份当前用户可见 JD，`multi_jd` 绑定 2–10 份；越界返回可理解 422 且不创建画像。新增 API 测试覆盖这两种场景
- [x] 2.4 聚合服务为每项要求保存来源证据，证据必须是对应 `Job.raw_jd` 子串；重复要求合并并保留各来源原文，无证据要求丢弃且拒绝原因不得包含 JD 正文。用测试覆盖合并与丢弃
- [x] 2.5 画像仅所有者可访问，其他用户得到 404 且不泄露来源 JD。用隔离测试验证
- [x] 2.6 画像用于生成后冻结快照；源 Job 后续修改不影响既有简历包，新生成请求使用更新后的画像版本。用快照隔离测试验证

## 3. 统一简历素材与原子事实

- [x] 3.1 扩展 `ExperienceEntry`：`kind` 覆盖 education、internship、employment、project、research、competition、award、certificate、skill；新增 `details_json`、`clarifications_json`、`completeness_score` 和 draft/confirmed 状态。`0009` 回填旧记录兼容值，`test_migrations.py` 通过
- [x] 3.2 扩展 `ResumeFact`：增加 `material_id`、`claim_type`、`evidence_json`；旧 `linked_fact_id` 与旧事实继续可读。迁移测试确认旧事实行可查询
- [x] 3.3 支持从空白建档，也支持 DOCX / 文本型 PDF 解析预填；未知字段保持为空，不得编造指标。扩展 `test_experience_library.py` 或新增素材测试覆盖这两条路径
- [x] 3.4 AI 只对缺失或含糊字段生成追问，不得替用户填写未知事实，素材保持未确认。用 mock LLM 测试断言追问字段集合
- [x] 3.5 确认完整素材时拆成角色、动作、工具、结果等单一主张的原子事实，并全部回链 `material_id`。测试断言多条 `user_confirmed` 事实
- [x] 3.6 仅来自范本、缺少本人核验信息的奖项或证书确认被拒绝并说明所需证据。沿用并扩展现有范本确认 422 用例
- [x] 3.7 编辑已确认素材后，受影响事实回到待确认，引用这些事实的简历包与指南标记过期；跨用户访问返回 404。新增测试覆盖这两条
- [x] 3.8 账号清理删除用户自有素材与原子事实，保留全站范本。扩展 `test_privacy.py` 并确认通过

## 4. 双轨简历包与生成管线

- [x] 4.1 新增 `ResumeBundle`、带 claim token 的生成运行记录，以及 `InterviewGuide` 表；`ResumeVersion` 增加 `bundle_id`、`target_profile_id`、`quality_report_json`、`content_hash`、`template_snapshot_json`，并允许多 JD 版本的 `job_id` 为空。Alembic `0010_add_resume_bundles_and_interview_guides` 升级/降级测试通过，旧版本无需回填 bundle
- [x] 4.2 定义 `content_version=3` bullet 合同：稳定 `id`、`text`、`source_fact_ids`、`source_target_ids`、`requirement_ids`、`achieved`、`locked` 和空的 `new_claims`。用 schema / 单元测试拒绝非法 bullet
- [x] 4.3 创建简历包 API 返回 202 与 bundle 状态；相同幂等键和请求哈希复用同一 bundle，不重复扣额或调用模型。新增 `test_resume_generation_v3.py` 覆盖创建、查询和重放
- [x] 4.4 进程内 worker 按 queued / generating / ready / degraded / failed 推进；维护任务可将中断的 generating 重新排队。用运行记录测试验证 claim token 与重入
- [x] 4.5 规划并写作同源双版本：真实能力版只引用已确认原子事实；蓝图未来项必须 `achieved:false`、引用当前画像 requirement，显示 `*`，且不得出现在真实版。用生成测试覆盖
- [x] 4.6 确定性 Fact Guard 对无来源主张拥有最终否决权，即使 LLM critic 给高分也不得进入 ready。扩展 `fact_guard` 相关测试
- [ ] 4.7 质量失败时最多两轮定向修复，修复历史写入质量报告；外部模型不可用时返回事实合规的本地基础版、bundle 标为 `degraded`，无法溯源的蓝图项直接省略。测试覆盖一轮修复成功和模型不可用降级
- [x] 4.8 支持按 bullet / section / all 重生成；`locked` bullet 在全局重生成中保持不变；任何编辑或重生成都重跑门禁、更新 `content_hash`，并使绑定旧哈希的指南过期。测试覆盖锁定与局部替换

## 5. 质量门禁与四类基准

- [x] 5.1 实现确定性硬门禁：来源完整、kind / achieved 语义、目标覆盖、单页预算、导出一致、ATS 文本可读；LLM 评分不得放宽硬门禁。单元测试覆盖 critic 放行但 Guard 拦截
- [x] 5.2 每个版本保存目标相关性、具体性、个人贡献、信息密度、可读性、ATS 和面试可辩护性分项，以及问题、修复历史、评审版本和内容哈希；用户可见报告不含完整模型 prompt。API 测试断言报告结构
- [x] 5.3 高优先级要求必须在真实版有事实证据，或在蓝图以未达成目标覆盖；未覆盖要求列入两版质量报告。测试覆盖 must-have 缺口
- [ ] 5.4 仅硬门禁通过的 `degraded` 版本可预览和导出，工作台显示降级提示且提示不得写入简历正文；版面失败阻止该格式交付。测试覆盖降级可导出与超页 PDF 不可交付
- [x] 5.5 用完全虚构数据覆盖机械制造、电子自动化、计算机数据、化学材料与生物医药四类质量基准；真实授权材料不得进入仓库、日志或固定测试。跑基准测试全部通过

## 6. 模板快照与三格式导出

- [x] 6.1 在应用内提供版本化 `classic-navy-ats-v2` JSON，不创建 `resume_templates` 表；生成时把模板配置快照写入 bundle / version。测试断言快照不含真实姓名、联系方式或完整个人经历
- [x] 6.2 分区顺序固定为求职方向、教育、实习/工作、项目/科研/竞赛、奖项证书、技能；空分区隐藏，教育背景紧接求职方向之后。渲染测试覆盖该顺序
- [x] 6.3 将 `resume_pdf/workflow` 的产品渲染与 PDF QA 并入 `apps/api`，运行时不再读取 `resume_pdf/resume_self/`。用路径断言或测试验证
- [x] 6.4 HTML 作为规范布局，DOCX 与 PDF 从同一 content 和快照生成；三种格式的章节、可见 bullet、未达成标记和正文文本一致，且不泄露内部来源 id 或质量元数据。扩展 `test_resume_exports.py`
- [x] 6.5 PDF 优先用 headless Chromium 打印 HTML，否则用 LibreOffice 转换 DOCX；两者都不可用时 HTML / DOCX 仍可导出，PDF 返回明确依赖错误。用测试或本地无转换器断言验证
- [x] 6.6 正式交付的 PDF 必须为 A4 单页、无裁切、字体嵌入、具有 Unicode 文本映射，并可提取全部可见章节和要点；超页不交付该 PDF 并返回生成修复流程。有转换器时跑 QA 测试
- [x] 6.7 蓝图未达成要点显示轻量上标 `*`，页脚恰好一次说明“`*` 为目标蓝图内容，尚未形成可核验经历”；真实能力版不得出现该说明。HTML / DOCX / PDF 一致性测试覆盖
- [x] 6.8 默认生成无照片版本；私有证件照是同一模板的可选输入，不得进入日志、模板快照或测试夹具。测试覆盖无照片导出仍通过单页布局
- [x] 6.9 默认模板颜色或间距更新后，旧版本再次导出仍使用创建时快照。新增回归测试并确认通过
- [x] 6.10 README 与启动文档不再把根目录 `resume_pdf/` 列为产品导出入口；人工确认文档

## 7. 面试指南

- [x] 7.1 bundle 硬门禁通过后，为真实能力版和蓝图 Plus 各排队生成一份绑定 `resume_version_id`、目标画像和内容哈希的指南。API 测试断言 bundle 返回两份指南状态
- [x] 7.2 真实能力版指南为每个可见 bullet 生成来源绑定的 claim card，包含主问题、连续追问、六段式讲法、个人贡献边界、核验材料和危险说法，并提供 60 / 90 秒自我介绍、JD 专业与行为题、岗位动机、反问清单和面试前检查表。测试三 bullet 恰好三张卡且引用事实来源
- [x] 7.3 蓝图指南覆盖每个 `achieved:false` 要点，列出可能被问穿的问题、当前诚实边界、缺少的证据和完成后应具备的答法，不得生成把未完成内容描述为已完成的回答。测试未取得奖项目标
- [ ] 7.4 可见 bullet 覆盖率 100% 为硬门禁；漏项触发修复或安全回退，补齐前不得 ready。测试模型漏一条 bullet
- [x] 7.5 绑定简历 `content_hash` 变化时旧指南立即标为 stale，并保留为历史记录直到新指南生成完成。测试编辑后过期
- [x] 7.6 第一阶段只提供指南查看和导出，不提供文字作答、自动评分、顾问评分或语音模拟入口；旧 Interview 接口保持兼容但不得混入新指南合同。API 与前端断言无作答入口

## 8. 自助工作台与导航收口

- [x] 8.1 新增 `/app/resume-studio`，按目标、素材、双版本、导出、指南五个连续区域组织流程；允许上传或空白建档。前端组件测试确认不同毕业年份用户看到同一流程
- [ ] 8.2 工作台提供 A4 预览、真实版与蓝图对比、逐 bullet 来源、质量问题、锁定、局部重生成、排序、撤销和版本对比；用户操作后看到重新校验状态。组件测试覆盖锁定后整份重生成
- [x] 8.3 事实与版面硬门禁通过的 ready 或 degraded 版本无需顾问批准即可由所有者预览和导出；degraded 在工作台显示质量降级提示。组件或 API 测试覆盖
- [x] 8.4 普通用户主导航只保留工作台、面试指南和账户设置；岗位看板、投递、学习目标、顾问运营和套餐额度退出主流程，但旧 URL 与已授权接口继续可访问。`Layout` / `App` 测试覆盖导航收缩和旧路由仍可打开
- [x] 8.5 工作台保存草稿与异步生成状态，刷新后从服务端恢复同一 bundle 进度且不发起重复生成；错误信息不得包含完整简历、JD、照片或模型 prompt。测试刷新恢复与错误脱敏
- [x] 8.6 旧投递、顾问、岗位和额度页面不删除。现有相关后端与前端测试保持通过

## 9. 种子、文档与总验证

- [x] 9.1 扩展 `seed_demo.py`，用虚构数据覆盖单 JD、多 JD 和四类理工科专业；确认不含真实授权材料。跑 dry-run 或种子测试
- [x] 9.2 更新 `docs/api.md`、`README.md` 和 `docs/product-spec.md`，使其与新接口、工作台和导出门禁一致。人工对照 spec 场景无矛盾
- [x] 9.3 新增自助主流程 e2e：创建目标画像 → 空白或上传素材并确认 → 生成双轨简历包 → 导出 HTML/DOCX（及可用 PDF）→ 打开两份面试指南
- [x] 9.4 跑后端相关 pytest、前端组件测试和受影响 e2e，确认旧接口兼容且无回归
- [x] 9.5 确认 Git 状态中无个人 PDF、JD dump、分析报告、`var/` 或渠道原始文件；测试夹具仅为虚构数据

## 10. 用户裁决：允许 AI 扩写（2026-09-05）

本节覆盖原 4.2、4.5、4.6、5.1、6.7 中仅限已确认事实的约束，其余未完成任务不属于本次范围。

- [x] 10.1 新生成的 v3 简历默认允许 AI 补充主张，事实不足不阻止生成、预览和导出；仍检查来源 ID 归属、内容结构及版面。
- [x] 10.2 扩写条目记录为 AI 待核验，工作台、导出和指南保留标识，不自动创建已确认事实；真实 Provider 收到材料和目标上下文。
- [x] 10.3 同步当前规则文档，并通过扩写、来源隔离、导出、回退和旧接口兼容测试。

本次验证：后端 259 项、前端 34 项、浏览器 E2E 3 项通过，生产构建通过。真实 Provider 协议通过本地 HTTP 替身验证，未调用收费外部模型。JSON 内容扩展不涉及数据库 schema 变更。

## 11. 工作台渐进式输入（2026-09-05）

- [x] 11.1 工作台默认只展示 JD 输入和生成主操作；岗位/画像历史不以长列表铺开，素材详情只在用户主动补充经历时展开。单 JD 一次点击完成岗位保存和画像创建，附加经历缩减为组织、自然语言描述和可选结果，并保留上传简历与多 JD 能力。组件测试和完整 E2E 覆盖默认收起与展开后的流程。验证：后端 264 项、前端 35 项、浏览器 E2E 3 项和生产构建通过。
