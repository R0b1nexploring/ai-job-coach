# 第19节真实模型与浏览器验收记录（2026-09-21）

> 使用完全虚构材料与真实 compatible Provider。本文只记录元数据、结构与差异，不含密钥、完整 Prompt 或完整简历正文。完整生成结果保存在 `tmp/section19-live/`（已 gitignore，供人工核对）。

## 环境

- 真实 Provider：`.env` 中 `LLM_PROVIDER=compatible`（模型名与密钥不在此记录）。
- 素材：虚构“虚构理工大学”课程项目与虚构 JD，均为测试用途。
- 脚本：`scripts/check_section19_live.py`（`--acknowledge-cost` 才会真实调用）。
- 浏览器/PDF：Playwright Chromium 已安装；`pdfinfo`/`pdftotext`/`pdffonts` 与 LibreOffice 可用。

## 首次生成：三类素材

| 用例 | 状态 | writer | reviewer | 求职版要点 | 蓝图要点 | 蓝图指南项目卡 |
| --- | --- | --- | --- | --- | --- | --- |
| rich_design | degraded | model/model | model/model | 7 | 7 | 1（practice_plan/purpose 齐全） |
| rich_process | degraded | model/model | deterministic/model | 2 | 3 | 1 |
| sparse_design | degraded | fallback/fallback | model/model | 2 | 2 | 2 |
| blank_design（生产门禁） | degraded | fallback/fallback | model/model | 2 | 2 | 2 |

- 空白素材不伪造身份/学校：`blank_design` 无任何已确认事实，仍生成可编辑草稿，`next_actions=['guide']`（“查看这个项目怎么做”）。
- 零散素材：`sparse_design` 使用一条未确认草稿即生成。
- 丰富素材：保留专业细节，蓝图项目卡含 `purpose` 与结构化 `practice_plan`（动作-产物-检查）。
- 记录到的失败：`blank_design` 在本地关闭质量门禁时两次 `fact_guard_failed`（真实模型输出了不属于上下文的来源 id）；启用生产门禁后经定向修复回退为 `degraded` 交付。`sparse_design` writer 回退为确定性基础版。均为真实失败/降级/修复样本。

## 同一素材、不同职责 JD 的差异

同一组虚构素材分别面向“机械结构设计工程师”和“机械工艺工程师”：

- 求职版引用要求 id 集合不同且基本不相交：设计 9 项、工艺 6 项（见下）。
- 蓝图要点数不同（设计 7、工艺 3），选材与篇幅随岗位职责变化。
- 两份蓝图指南的项目卡均含 `practice_plan` 与 `purpose`，围绕各自岗位角度。

设计引用：`272ae5bb…, 31fcbd03…, 4480f960…, 687ae9ce…, 960dda01…, 96473fb7…, 9cf68763…, e425c572…, eab7d7b5…`
工艺引用：`3b54052c…, 4257abbb…, 5d7baea0…, cbd8915d…, d598c0ac…, ff533df2…`

## 后续更新（rephrase 派生）

- `rich_design_rephrase`：status=ready，求职版 writer=model，蓝图 writer=copied。
- 蓝图正文逐字节复制父包（同一组 requirement id、同一 headline、`achieved_false` 数不变）；求职版仅按所选要点换表达，父包保持不变。
- 派生包指南绑定自身版本/哈希（语义未变 ready）。

## 浏览器与文件交付（19.13）

- Playwright：`admin-operations`、`main-flow`、`studio-flow` 3 条 E2E 全部通过；`studio-flow` 覆盖一次点击生成、双版切换、HTML/DOCX/PDF 下载、两份指南打开、390px 窄屏。
- Chromium PDF：`test_resume_generation_v3` / `test_resume_exports` 在 `converter_available()` 为真时经 `inspect_pdf_bytes` 校验 A4 单页、无裁切、字体嵌入、Unicode 文本层；当前环境 Chromium 打印路径可用并通过。
- 未在真实模型下同时下载两版三格式：E2E 使用 mock Provider（配置强制）。真实 Provider 的正文与指南差异见上表；文件物理门禁由 Chromium 路径覆盖。

## 说明

- 本地开发默认 `RESUME_QUALITY_GATE_ENABLED=false`；验收采用生产门禁语义，故 blank 用例在门禁开启下判定交付。
- 本记录为验收证据，不代表生产部署或邀请试用条件已满足。

## spec 对照审计（2026-09-21 第二轮）

### 已修正的出入

1. **supplement 只改一版** → 现按素材引用跟踪：同一 source_fact_ids 也出现在另一版时，两版同步更新；其余意图仍只作用于所选版本。
2. **retarget 未保留锁定项** → 现 `_restore_parent_locked` 在重新选材后把父包锁定要点按内容/位置/归属放回，并重新评审。
3. **writer/critic/guide 未共享同一策略** → `writing_brief` 与 `writer_profile.resource_boundary` 现同时进入 writer、critic 与指南的模型输入；简报与画像持久化到 `generation_metadata_json`；派生包继承父包策略。

### 仍存在的出入（未在本轮实现，按主计划归属后续任务）

1. **布局（排版）派生**：`/edits` 支持 content/lock/reorder，未提供 layout 操作；`resume-export` 的“布局变化重新生成并检查文件”尚未落地。
2. **历史基线保护范围**：旧工作台写入口（`/resume-versions/{id}/lock|reorder|regenerate`、workflow `PATCH`）仅在包“已有子包”时返回 409；新交付包仍可被旧入口原地改写。新 `/edits` 始终派生。彻底满足“所有 v3 写入口先派生”需要把工作台切到 `/edits`（前端改动）。
3. **首次发起的服务端持久衔接**：首页“生成我的简历”是前端串行（保存 JD → 建画像 → 建包），页面在两步之间关闭时前序步骤不会服务端恢复；上传解析失败的重试/跳过未在该链路呈现。统一 `tasks` 表（17.2）已存在，但首次编排尚未映射上去。
4. **“调整篇幅”内容调整**：`resume-export` 要求的主动异步调整动作尚未实现（原属 17.19/R4），因此“先派生再导出”也无可接入点。
5. **策略传递的边角**：`regenerate_scope` 与 `_restore_parent_locked` 的复评未带策略参数（不影响交付门禁）。

