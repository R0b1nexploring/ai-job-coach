## Context

已提交的 MVP-1 把简历内容存在 `ResumeVersion.content_json`，版式写死在 `resume_style.py` 与 HTML/DOCX 渲染器。工作区另有未提交的经历库、校招简章（含 Alembic `0008`），以及根目录 `resume_pdf/`：其 `template_profile.json` 才是真正的版式模板，但没有进数据库，也没有被主应用导出使用。

约束：`docs/plan-target-resume-loop.md` 与 `PROJECT_SPEC.md` §27 对蓝图/可投递、Fact Guard、渠道「只导入不爬」仍然优先。本设计只解决未提交表面的落点和模板进库，不重开那些裁决。经历库与简章的工作区实现大体可对齐 spec，应在其上收敛，而不是另起一套模型。

## Goals / Non-Goals

**Goals:**

- 经历、简章、简历模板都成为可引用的目录数据；用户数据与系统目录用 `owner_user_id is NULL` 区分。
- 简历导出只读版本上的模板快照，主应用不再依赖根目录 `resume_pdf/`。
- 迁移可在空库升级；默认模板不依赖 `seed_demo.py`。
- Git 边界与隐私清理覆盖新表。

**Non-Goals:**

- 用户自建或多套换肤模板。
- 把 `scripts/fetch_job_jds.py` 或 `data/jd_collection.json` 升级为 Job Provider。
- 改 Fact Guard、匹配公式、邮件草稿发信。
- 把 LibreOffice 变成本地开发的硬依赖。

## Decisions

### 1. 系统目录统一用「空归属」而不是独立表家族

经历范本、共享简章、系统简历模板都用 `owner_user_id` 为空表示全站目录，与已有 `application_channels` 一致。

备选：范本/模板另表。否决原因是查询与清理规则已经按空归属工作，再拆表只会让 `0008` 与隐私逻辑分叉。

### 2. 简历模板单独建表，版本保存快照

新增 `resume_templates`：`id`、`slug`（唯一）、`name`、`version`、`owner_user_id`（本轮恒为空）、`profile_json`、`status`（`active`/`retired`）。

`resume_versions` 增加可空 `template_id`（FK）和 `template_snapshot_json`。生成或首次导出时写入；之后导出只读快照。

备选：只把 `profile_json` 拷进版本、不建目录表。否决原因是无法稳定引用「默认模板」，也无法在不改历史版本的前提下迭代版式。

备选：版本只存 `template_id`、每次读直播目录。否决原因是改模板会改写已审核导出，破坏顾问审核与投递留痕。

`profile_json` 沿用现有 `template_profile.json` 形状（`page` / `typography` / `colors` / `layout`）。快照保存逻辑字体与候选列表；渲染时在当前机器上解析可用中文字体。跨 OS 字形可以不同，颜色、页边距、栏位和未达成标记必须相同。

### 3. 迁移拆成 `0008` + `0009`

- `0008`：经历库与简章（工作区已有，幂等 `inspect` 风格，对齐既有 SQLite 重建窗口）。
- `0009`：`resume_templates`、`resume_versions.template_id`、`resume_versions.template_snapshot_json`，并插入 `slug=classic-navy-ats-v1` 的默认行。

备选：把模板塞进未提交的 `0008`。否决原因是 `0008` 已有测试与 head 文档，模板是新的数据合同；拆开便于失败时单独回滚模板列。

存量版本不在迁移里回填快照，避免迁移读取渲染代码。首次导出或下次生成时补写。

### 4. 渲染代码迁入应用后端，根目录不再是产品入口

将 `resume_pdf/workflow` 的渲染、校验、QA 并入 `apps/api/app/services/`（扩展现有 HTML/DOCX 渲染器，使它们吃 `profile_json` 而不是模块级常量）。产品测试放在 `apps/api/tests/`。

根目录 `resume_pdf/` 不再作为正式导出入口。`resume_self/` 与 `private/` 继续 Git 忽略，应用运行时不得读取。虚构示例 JSON 可迁到 `apps/api` 测试夹具。

PDF：HTML/DOCX 必须在无 LibreOffice 时可用；PDF 在转换器可用时用同一快照生成，否则返回明确错误。

### 5. 经历库继续挂在「经历库简历」上

保持工作区做法：每用户一份 `parse_status=library` 的系统简历，确认后的经历写成挂在其上的 `ResumeFact`（`provenance=user_added`）。简历生成读取「当前选中简历的已确认事实 ∪ 经历库已确认事实」。

从范本复制只拷结构，清空组织与正文；确认时拒绝范本虚构单位。上传简历中已确认的实习/项目回写经历库，`source=original_resume`。

备选：经历不写 `ResumeFact`、生成时另查经历表。否决原因是 Fact Guard 与匹配已经按事实 ID 工作，另开通道容易漏校验。

### 6. 简章导入复用渠道安全校验

`import_jobs.py` 默认 dry-run；`--execute` 才写入。投递入口走现有渠道导入的 HTTPS/DNS/邮箱规则：渠道失败时简章仍保存、`channel_id` 为空。岗位按岗位名拆出并关联 `announcement_id`。共享简章拆出的岗位 `owner_user_id` 为空，匹配与列表走可见性而不是「仅自己创建」。

不提供简章爬取 API；`fetch_job_jds.py` 与 JD dump 不进入产品路径。

### 7. 清理与忽略

账号清理删除该用户的 `experience_entries`、其私有简章，以及其简历版本（含快照）。系统范本、系统模板、共享简章保留。

`.gitignore` 保持并提交：`tmp/`、`output/`、`resume_pdf/resume_self/`、`resume_pdf/private/`、`data/channel-imports/*`。`data/jd_collection.json` 与调研报告不加入版本控制。

## Risks / Trade-offs

- [工作区已有实现与 spec 不完全同构] → 以 spec 为准收敛：尤其是「完整自建经历立即确认」与「范本副本必须确认」两条路径，测试必须同时覆盖。
- [模板快照较大] → 单套 profile 体积很小；不把 PDF/照片放进 JSON。
- [跨机器字体解析不一致] → 接受字形差异；用快照锁定度量与颜色，测试断言 A4、未达成标记和章节数，不断言具体字体文件名。
- [PDF 依赖外部转换器] → 保持可选；CI 以 HTML/DOCX 为门禁。
- [可见岗位范围变大] → 共享简章岗位对所有登录用户可见，测试必须断言私有简章仍隔离，且匹配不能引用不可见岗位。

## Migration Plan

1. 提交 `.gitignore` 更新，确保私人样张与 dump 不会进入后续提交。
2. 落地 `0008`（经历 + 简章）及对应 API/前端/测试。
3. 落地 `0009`（模板表 + 默认行 + 版本列），迁移渲染器，导出改读快照。
4. 种子只负责虚构经历范本与虚构简章样例；默认简历模板由 `0009` 插入。
5. 回滚：`0009` 降级删除列与表，导出回退到代码内默认 profile；`0008` 降级删除经历/简章表。不回放已忽略的私人文件。

## Open Questions

- 默认模板是否允许运营者在后台改 `profile_json`，还是本轮只能通过迁移替换。本轮按「仅迁移/种子更新」实现，不新增管理 UI。
