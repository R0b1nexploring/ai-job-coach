# Project instructions

- 需求来源与优先级（**冲突时按此顺序裁决**）：
  1. `docs/plan-resume-interview-core.md` —— 自助简历、目标画像、双轨生成、导出和面试指南的当前实施依据。涉及这些能力时**本文件优先**。
  2. `docs/plan-target-resume-loop.md` —— 旧目标简历闭环与投递渠道的历史实施记录。仅在新计划未覆盖的投递/渠道细节上参考，不得否掉第 1 条。
  3. `PROJECT_SPEC.md` 与 `docs/product-spec.md` —— 其余全部产品需求的来源。
- `PROJECT_SPEC.md` §28 记录了本轮方向裁决；§27 是上一轮与 §21.4 / §22 的冲突记录，**开工前必读**。
- `docs/plan-target-resume-loop.md` 第 2 节的阶段 0（数据模型 + Alembic `0004`）**已完成并在工作区，不要重做**，直接在其上继续。
- Run the relevant tests after every change.
- 新工作台 v3 默认允许 AI 扩写，不以缺少事实支持阻止生成或导出；AI 补充保留待核验状态，不写成已确认事实。详见 `PROJECT_SPEC.md` §28.4。
- Never treat AI-generated text as a verified fact.（蓝图简历中未达成的条目必须带 `achieved: false` 标记并在渲染时可见，这是本条的落实方式，不是例外。）
- Every database schema change requires an Alembic migration.
- Every external service needs a Base Provider and a safe local fallback; payment uses Disabled Provider in MVP-1.
- Never put secrets or complete resume contents in code or logs.
- User-facing copy is clear Chinese; code identifiers are English.
