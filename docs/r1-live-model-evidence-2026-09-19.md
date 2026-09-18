# R1 真实模型证据（2026-09-19）

对应 tasks 17.3、17.4、17.5。本记录只覆盖真实模型链路，与 mock/协议测试分开。
所有输入均为完全虚构材料，不含真实个人简历。

## 环境

| 项 | 值 |
| --- | --- |
| commit | 见文末提交 |
| Provider | `LLM_PROVIDER=compatible` |
| endpoint | 本地 OpenAI 兼容桥 `http://127.0.0.1:4000/v1` |
| 模型 | `deepseek-v4.1-flash`（cheap 与 strong 同一模型） |
| 脚本 | `scripts/compare_project_story_loop.py --case <sparse|blank> --acknowledge-cost` |
| 产物 | `tmp/generated/project-story-compare-*/`（Git 忽略，未提交） |

说明：`.env` 的 `LLM_API_KEY` 为空，公网 DeepSeek 不可用；本地桥提供真实模型推理，
但不是生产 Provider 验收。生产真实 Provider 验收仍待第 12/17.23 节。

## sparse 用例（1 条虚构事实）

- 结果：`before` 与 `after` 均为 `hard_passed=True`，reviewer 为 `model`。
- `after` 蓝图项目四要素全部具体（situation/task/actions/result 均为 true），
  3/3 行动带具体方法，`achieved=False`。
- 未见 `star_diagnostics` 或 `visible_coverage` 诊断。

## blank 用例（无素材）

修复前的真实运行暴露两个实现缺陷，均已修复：

1. **部分评审被当成 ready。** 真实 critic 未返回分项评分时，bundle 仍标为 `ready`，
   违反「缺维度未评估、内容合格按 degraded 交付」。修复：`critic_status`
   区分 complete/partial/unavailable，非 complete 一律 `degraded` 并内部记录缺项。
2. **未解决的语义问题直接 failed，未走合格回退。** 修复：先对相关版本使用
   确定性回退并重新检查；回退仍带已定位语义错误时才算 `failed`。
3. 同时收紧了 critic 提示：蓝图项目按设计即为未来计划（`achieved=false`、
   `kind=target` 指标），不得判为矛盾；`issue_code` 只用于三类实质内容错误。

修复后的真实运行结果：

| 指标 | after |
| --- | --- |
| bundle_status | `degraded` |
| 内部记录 | `critic_partial_submittable:...`、`critic_partial_target:...` |
| 蓝图四要素 | situation/task/actions/result 全部具体 |
| 行动 | 3/3 带具体方法 |
| achieved | `false`，`verification_status=ai_generated` |
| 用户可见 | 主界面不显示评分、降级原因或诊断 |

生成内容示例（虚构）：背景说明「信息不足」，角色为「计划负责人（个人承担建模、装配、出图与记录编写）」，
三个行动分别给出 SolidWorks 建模装配与工程图验证的具体方法，结果为零件/装配体模型、二维工程图和
覆盖定位/夹紧/干涉/可达性的验证记录，并明确「全部为计划验证方式，无实测指标」。

## 未完成

- 真实 critic 仍未返回分项评分（7 个维度均未评估），因此真实链路稳定停在 `degraded`；
  这是供应商输出质量问题，本实现不补假分，按合同记为 partial。
- 公网真实 Provider（DeepSeek）未验证：无 API key。
- 多项目与无数值成果的真实模型对照尚未单独执行；mock 用例已覆盖
  （`tests/test_star_delivery_contract.py`）。
- 指南未纳入本次真实对照（沿用 15.14 的未完成状态）。
