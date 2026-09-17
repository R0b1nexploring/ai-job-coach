# 项目 STAR 真实模型对照记录（2026-09-17）

本文记录 tasks 第 15.14 项的真实模型对照：使用同一组**完全虚构**输入，对比“无项目方案输入 / 旧提示”与“当前方案前置 + 设计边界”两条链路生成的内部项目方案与简历正文，并做人工检查。所有材料均为虚构，未使用任何真实简历、真实账号或真实 JD；产物落在 gitignored 的 `tmp/generated/`，不进入仓库。

## 方法与命令

- 脚本：`scripts/compare_project_story_loop.py`（`_compose_pair` 直连 v3 管线）。
- 变体 A（before）：阻断 `build_project_story_inputs`（返回空）并去掉本轮新增的 `design_supplement`／`open_questions` 提示行。
- 变体 B（after）：当前实现。
- 用例：`sparse`（一段已确认夹具项目事实）、`blank`（无任何素材，仅目标画像）。
- Provider：`.env` 中的 `compatible`（本地 `http://127.0.0.1:8317/v1`，模型 `gpt-5.6-luna`）；`RESUME_QUALITY_GATE_ENABLED=true` 覆盖本地调试开关，使质量硬门禁生效。
- 脚本会在写作者返回本地回退时重试（最多 5 次），只对两侧都来自真实模型的结果做质量对照，避免把回退内容当成模型效果。

命令：

```bash
for c in sparse blank; do
  RESUME_QUALITY_GATE_ENABLED=true \
    apps/api/.venv/bin/python scripts/compare_project_story_loop.py \
    --acknowledge-cost --case "$c" --verbose
done
```

## 结果

| 用例 | 变体 | bundle | 写入来源 | 重试 | 项目方案具体度 | 可见覆盖诊断 | 模型评审 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sparse | before | degraded | 真实模型 | 2 | S/T/A/R 全具体，3/3 行动完整 | 无 | critic 不可用，退回确定性 |
| sparse | after | ready | 真实模型 | 1 | S/T/A/R 全具体，3/3 行动完整 | 无 | 返回项目级评审与建议 |
| blank | before | degraded | 本地回退 | 5 | 占位方案，四要素缺项被逐条定位 | 无 | 模型仍给出“这是计划非经历”的评审 |
| blank | after | degraded | 本地回退 | 5 | 占位方案，四要素缺项被逐条定位 | 无 | 同上，边界更明确 |

## 人工检查结论

- **具体性**：sparse 两版方案均达到项目级具体度（含场景、角色、方法、取舍、难点、交付物与验证方式），并附带 `design_assumptions` 与 `open_questions`；`after` 的背景更明确指向“是否已形成独立验证记录”的缺口，行动粒度更细。
- **压缩丢失**：两版可见 bullet 均保留了任务与结果（如“补充设计验证记录，说明关键结构取舍与检查方法”），未退化成纯工具清单；本地 `visible_coverage.*` 未触发。
- **因果与边界**：`after` 的模型评审明确指出第二条 bullet 是计划而非既成事实，并给出“拆分已完成事实与后续计划、补充真实取舍与可核验结果”的建议，符合“本地硬门禁 + 模型解释性评审”的分工；`achieved:false` 与蓝图未达成标识保持。
- **无素材场景**：blank 两侧写作者均返回本地回退，蓝图退化为占位方案，但本地诊断逐条列出缺失要素，模型评审也明确判定“不是可验证经历”，未把目标包装成已完成事实。

## 与 mock/规则测试分开报告的问题

- **Provider 结构化输出不稳定**：`resume_rewrite` 多次返回 `LLM_MALFORMED_RESPONSE`（直连探测约 1/4 概率），触发安全本地回退；blank 用例连续 5 次未获得模型输出。该现象与本轮代码改动的输入量增大相关但无法在 mock 环境复现，需要真实 Provider 稳定性或输出上限支持。
- **critic 分项评分为空**：所有成功的模型评审都只返回 `summary` 与 `project_reviews`，未返回 `dimensions`，因此各维度得分为空（`assessed=false`），本地未补假分。这暴露了评审任务的结构化输出契约缺口。
- **示例规模有限**：sparse 各 1 次有效样本，模型方差可能主导差异；blank 未取得真实模型样本。结论只用于记录问题，不作为质量已验收的证据。

## 未完成

- 指南未纳入本次真实模型对照（本次只生成方案与简历正文）；指南此前由 mock/规则测试覆盖。
- 15.14 保持未勾选；15.3、15.4 维持重新打开。需要真实 Provider 更稳定后，再补充“方案 → 简历 → 两份指南”的完整同源对照。
