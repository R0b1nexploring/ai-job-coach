# 产品规格

> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

本文件是产品规格入口，不复制完整正文，避免形成分叉。一般需求以根目录 [`PROJECT_SPEC.md`](../PROJECT_SPEC.md) 为准；涉及目标画像、素材确认、双轨简历、导出和面试指南时，以 [`plan-resume-interview-core.md`](plan-resume-interview-core.md) 和 `PROJECT_SPEC.md` §28 为当前实施依据。旧计划 [`plan-target-resume-loop.md`](plan-target-resume-loop.md) 与 §27 保留为历史记录。

2026-09-12 本轮以 [`plan-resume-interview-core.md`](plan-resume-interview-core.md)「本轮执行范围」及 `PROJECT_SPEC.md` §30 为准：最高优先级是完整、具体、连贯的蓝图项目 STAR 文案，其次是基于同一项目说明与简历正文的两份面试指南。当前入口为自助简历工作台，复用已有 JD/画像与可选素材，生成求职版和蓝图 Plus。设计指标不作为真实成果，AI 文案不自动进入已确认事实库。

用户成稿修改移入未来 TODO；岗位信息建设、公共岗位库和邀请试用上线本轮暂缓，不主动删除旧功能。素材录入继续可用。本轮不新增阶段完成条件或发布评分阈值；具体技术设计及实施任务见当前 OpenSpec change 的 design 和 tasks 第 15 节，未来 TODO 见第 16 节。

旧校招简章、投递渠道和顾问能力仅保留兼容，不属于本轮主流程。蓝图项目保留未达成标识，指南解释行动依据、技术追问、结果验证和实践准备；第一阶段不提供模拟答题或评分功能。
