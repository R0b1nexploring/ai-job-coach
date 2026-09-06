## Why

> **暂停执行（2026-09-05）**：产品方向已由 `focus-resume-interview-core` 接管。仓库卫生与简历导出收口迁入新 change；校招简章、投递渠道及其后续完善进入 backlog。本 change 保留为历史设计参考，不再作为当前实施依据。

本地工作区在已提交的 MVP-1 之上堆了三周未拆分的改动：经历库、校招简章、简历排版，以及根目录的 `resume_pdf` 旁路。这些能力已经能跑，但没有一份能裁决「什么进产品、什么进数据库、什么进 Git」的规格。现在补规格，是为了按边界落地，而不是把实验、抓取结果和个人样张一起提交。

## What Changes

- 把实习/项目经历提升为一等公民记录：用户可维护自己的经历，全站虚构范本只供对照；确认后才写入已确认事实库。
- 把校招简章做成共享目录：一行公司公告含岗位列表与投递入口；只允许运营者导入许可表格，不爬取第三方看板。
- 把现有 `resume_pdf` 版式提升为数据库中的简历模板目录，而不是根目录旁路产品。`ResumeVersion` 绑定模板并保存生成时的版式快照；主应用 HTML/DOCX（以及可选 PDF）都读同一份快照。
- 渲染代码迁入 `apps/api`，废弃根目录 `resume_pdf/` 作为产品入口。个人样张、真实输入 JSON、抓取 JD dump 不得入库、不得提交。
- 明确仓库卫生：虚构样例可提交；`var/`、`tmp/`、`output/`、个人 PDF、渠道原始文件、调研抓取结果保持忽略或排除。

本 change **不**改变蓝图/可投递双产物、Fact Guard 语义、投递渠道「只导入不爬取、邮件只出草稿」的既有裁决。

## Capabilities

### New Capabilities

- `experience-library`: 实习与项目经历库、全站虚构范本、确认后写入事实库的规则
- `campus-announcements`: 校招简章看板、许可表格导入、拆出岗位与投递渠道
- `resume-export`: 系统简历模板目录、版本绑定与快照、统一 HTML/DOCX/PDF 导出
- `repository-hygiene`: 可提交、须忽略、禁止入库的路径与材料边界

### Modified Capabilities

- 无。OpenSpec 主规格目录目前为空；`PROJECT_SPEC.md` 与 `docs/plan-target-resume-loop.md` 仍是产品需求来源，本 change 落地后再 sync。

## Impact

- 数据模型：`experience_entries`、`campus_announcements`（工作区已有未提交迁移 `0008`）、新增 `resume_templates`，`resume_versions` 增加模板引用与快照。
- API：经历库 CRUD/确认、简章列表与详情、导出读取模板快照；简章导入走运营脚本，不提供爬取接口。
- 前端：经历页、岗位/简章看板、简历导出沿用选定模板。
- 代码位置：`resume_pdf/workflow` 并入 `apps/api` 渲染与 QA；`resume_pdf/resume_self` 与 `resume_pdf/private` 保持本地忽略。
- 仓库：更新 `.gitignore` 与种子/样例策略；不提交 `data/jd_collection.json`、岗位分析报告、个人简历 PDF。
- 兼容：已提交的 MVP-1 导出路径继续可用；未指定模板的版本回落到系统默认模板并补快照。
