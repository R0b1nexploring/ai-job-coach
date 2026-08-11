# Project instructions

- 需求来源与优先级（**冲突时按此顺序裁决**）：
  1. `docs/plan-target-resume-loop.md` —— 目标简历闭环与投递渠道的当前实施依据。涉及简历生成、事实校验、学习目标、面试指南、投递渠道时**本文件优先**。
  2. `PROJECT_SPEC.md` 与 `docs/product-spec.md` —— 其余全部产品需求的来源。
- `PROJECT_SPEC.md` §27 记录了本轮与 §21.4 / §22 的已知冲突及裁决结果，**开工前必读**。
- `docs/plan-target-resume-loop.md` 第 2 节的阶段 0（数据模型 + Alembic `0004`）**已完成并在工作区，不要重做**，直接在其上继续。
- Run the relevant tests after every change.
- Never treat AI-generated text as a verified fact.（蓝图简历中未达成的条目必须带 `achieved: false` 标记并在渲染时可见，这是本条的落实方式，不是例外。）
- Every database schema change requires an Alembic migration.
- Every external service needs a Base Provider and a safe local fallback; payment uses Disabled Provider in MVP-1.
- Never put secrets or complete resume contents in code or logs.
- User-facing copy is clear Chinese; code identifiers are English.
