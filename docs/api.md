# API

启动后访问 `http://localhost:8000/docs` 查看实时 OpenAPI 文档。接口统一使用 `/api` 前缀；错误响应为 `{ "error": { "code", "message", "details", "request_id" } }`。

MVP-1 不暴露订单创建、支付回调或退款接口。`GET /api/packages` 用于展示说明，`GET /api/quotas` 与 `GET /api/quotas/ledger` 用于查询演示额度；管理员通过 `POST /api/admin/quotas/grant` 发放额度。Payment Provider 固定为 Disabled，并返回 `PAYMENT_NOT_AVAILABLE`。

JD 结构化、匹配解释、事实提取、学习目标、双版本简历、面试指南和邮件草稿都通过统一的结构化 LLM Provider。默认使用可重复的 Mock；`LLM_PROVIDER=compatible` 时调用环境变量配置的兼容 Chat Completions 服务，并校验 Pydantic 输出模型。配置不完整、请求失败或结构无效时回退到 Mock。响应与审计数据只记录 Provider 名称或错误类别，不记录密钥、完整 Prompt 或完整简历。

## 简历事实与待补信息

简历解析后，工作和项目事实会拆成结构化字段。缺少组织、角色、地点或日期时，前端读取 `missing_information_json` 并提交：

```text
POST /api/resumes/{resume_id}/answer-clarifications
```

请求体是 `{fact_id, field, value}` 数组；`field` 只允许 `organization`、`role_title`、`location`、`start_date`、`end_date`。回答后事实回到待确认状态。`POST /api/resumes/{id}/confirm-facts` 在关键字段仍缺失时返回 `409 RESUME_FACTS_INCOMPLETE`，并在 `details.missing_information` 给出待补项。

## 学习目标闭环

```text
POST  /api/matches/{match_id}/capability-targets
GET   /api/capability-targets?job_id={job_id}&status={status}
PATCH /api/capability-targets/{target_id}
```

生成接口按匹配报告幂等，目标包含 JD 原文证据、可展示产出物、验收标准和预计工时。状态为 `pending`、`in_progress`、`achieved` 或 `abandoned`。标记 `achieved` 必须提交非空 `evidence_text`；系统据此新增一条 `provenance=learned`、`verification_status=user_confirmed` 的事实，已达成目标不能回退。

## 蓝图简历与可投递简历

`POST /api/resume-versions` 请求体新增 `kind` 字段（省略时默认为 `submittable`），取值为：

- `target`：蓝图简历，可引用未达成学习目标；每条必须有 `source_target_ids` 且 `achieved=false`。
- `submittable`：可投递简历，只能引用用户已确认事实；每条必须有 `source_fact_ids` 且 `achieved=true`。

两类版本都运行 mode-aware Fact Guard，返回 `kind`、`unachieved_count`、`guard_status` 和 `fallback_used`；逐条检查与质量问题记录在 `traceability_json.guard_items`、`new_claims` 和 `quality_issues`。蓝图中的未达成内容必须在预览与 DOCX 中可见，不会被伪装成已有能力。

## 简历审核与导出

用户可通过 `POST /api/resumes/{id}/facts` 补充真实经历。新增或修改后的事实会回到待确认状态，并立即撤销该简历的整库确认标记；用户重新确认后才能生成新的定制版本。

```text
POST /api/resume-versions/{id}/submit-review
POST /api/advisor/resume-versions/{id}/review
GET  /api/resume-versions/{id}/preview
GET  /api/resume-versions/{id}/download
GET  /api/resume-versions/{id}/download?format=html
```

普通用户只能提交审核，不能自行批准。顾问只能审核被分配客户；Fact Guard 未通过时不能批准。预览、HTML 下载、DOCX 下载以及携带该版本进入投递队列，都要求 `guard_status=passed` 且 `review_status=approved`。

`POST /api/applications` 可选传入 `channel_id`，将投递记录关联到用户可见且未失效的公司级入口。蓝图版本不会因 `unachieved_count>0` 被后端硬阻断；前端会按 version + job 组合只提示一次风险清单。

HTML 输出对用户内容做实体转义，并返回限制性的 Content Security Policy。单页版使用 A4 打印样式，用户可在浏览器中打印为 PDF。

## 模拟面试

```text
POST  /api/interviews                         生成题目（支持 Idempotency-Key）
PATCH /api/interviews/{id}/answers            保存草稿回答
POST  /api/interviews/{id}/submit             锁定回答并提交顾问
POST  /api/advisor/interviews/{id}/score      顾问评分与复盘
```

只有 `draft` 状态可以修改回答；至少填写一条回答后才能提交；只有已分配顾问或管理员能评分 `submitted` 状态的面试。关联定制简历时，该版本必须已经通过 Fact Guard 和顾问审核。

## 岗位发布日期

人工导入岗位可选填 `published_at`。未提供时保存为未知，并在匹配时按规格计入 `2/5` 时效分；系统不会把导入时间冒充为岗位发布时间。

## 公开岗位发现

`POST /api/jobs/discover` 支持本地样例、公开企业合集、Greenhouse、Lever，以及
白名单公开招聘页。使用 `public_jsonld` 时，`source_key` 必须是最终 HTTPS URL，
且域名已配置在 `JOB_SOURCE_ALLOWED_HOSTS`，或来自未标记失效的已导入公司招聘页渠道。

白名单页面 Provider 只读取页面公开提供的 schema.org `JobPosting` JSON-LD，
遵守 `robots.txt`，拒绝 IP URL、本机或私网解析结果、重定向、非 HTML 和超大响应。
读取失败时接口明确返回 `fallback_used=true` 与错误原因，并使用本地虚构样例；
不会把回退数据标成真实抓取结果。

## 投递渠道与邮件草稿

```text
GET  /api/channels?search={company}&channel_type={career_page|email|form}
POST /api/channels/{channel_id}/discover-jobs
POST /api/channels/{channel_id}/report-dead
POST /api/applications/{application_id}/email-draft
```

渠道是公司级投递入口，不是岗位 Provider。`discover-jobs` 仅接受 `career_page` 渠道，提交 `{resume_id, limit}` 后仍走 `public_jsonld` 的 HTTPS、DNS、公网地址、robots、响应类型和大小检查。累计 3 次失效反馈后渠道变为 `dead` 并立即退出动态允许列表。

邮件渠道只返回草稿：`to`、`subject`、`body`、`attachment_hint`、`mailto_url`、`warnings` 和匹配点溯源状态。系统没有发信、SMTP、附件上传或批量投递接口。匹配点最多 3 条且只能引用已确认事实；不足 2 条时返回提醒。若 `mailto:` 编码后超过 2000 字符则 `mailto_url` 为空。关联蓝图简历时，正文仍只写已达成事实，并在 `warnings` 标出附件的未达成数量。

## 个人数据权利

`GET /api/account/export` 下载包含档案、事实库、学习目标、岗位、匹配、定制版本、投递、面试和额度记录的完整 JSON，不暴露内部文件路径。`DELETE /api/account` 提交删除请求，管理员通过 `POST /api/admin/accounts/{user_id}/purge` 擦除原始文件和派生个人内容。全局渠道属于公司数据，不进入个人保留期清理；`owner_user_id` 非空的私有渠道会随该用户清理。
