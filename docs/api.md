# API

启动后访问 `http://localhost:8000/docs` 查看实时 OpenAPI 文档。接口统一使用 `/api` 前缀；错误响应为 `{ "error": { "code", "message", "details", "request_id" } }`。

MVP-1 不暴露订单创建、支付回调或退款接口。`GET /api/packages` 用于展示说明，`GET /api/quotas` 与 `GET /api/quotas/ledger` 用于查询演示额度；管理员通过 `POST /api/admin/quotas/grant` 发放额度。Payment Provider 固定为 Disabled，并返回 `PAYMENT_NOT_AVAILABLE`。

## 简历审核与导出

```text
POST /api/resume-versions/{id}/submit-review
POST /api/advisor/resume-versions/{id}/review
GET  /api/resume-versions/{id}/preview
GET  /api/resume-versions/{id}/download
GET  /api/resume-versions/{id}/download?format=html
```

普通用户只能提交审核，不能自行批准。顾问只能审核被分配客户；Fact Guard 未通过时不能批准。预览、HTML 下载、DOCX 下载以及携带该版本进入投递队列，都要求 `guard_status=passed` 且 `review_status=approved`。

HTML 输出对用户内容做实体转义，并返回限制性的 Content Security Policy。单页版使用 A4 打印样式，用户可在浏览器中打印为 PDF。

## 模拟面试

```text
POST  /api/interviews                         生成题目（支持 Idempotency-Key）
PATCH /api/interviews/{id}/answers            保存草稿回答
POST  /api/interviews/{id}/submit             锁定回答并提交顾问
POST  /api/advisor/interviews/{id}/score      顾问评分与复盘
```

只有 `draft` 状态可以修改回答；至少填写一条回答后才能提交；只有已分配顾问或管理员能评分 `submitted` 状态的面试。

## 个人数据权利

`GET /api/account/export` 下载包含档案、事实库、岗位、匹配、定制版本、投递、面试和额度记录的完整 JSON，不暴露内部文件路径。`DELETE /api/account` 提交删除请求，管理员通过 `POST /api/admin/accounts/{user_id}/purge` 擦除原始文件和派生个人内容。
