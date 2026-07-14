# API

启动后访问 `http://localhost:8000/docs` 查看实时 OpenAPI 文档。接口统一使用 `/api` 前缀；错误响应为 `{ "error": { "code", "message", "details", "request_id" } }`。

MVP-1 不暴露订单创建、支付回调或退款接口。`GET /api/packages` 用于展示说明，`GET /api/quotas` 与 `GET /api/quotas/ledger` 用于查询演示额度；管理员通过 `POST /api/admin/quotas/grant` 发放额度。Payment Provider 固定为 Disabled，并返回 `PAYMENT_NOT_AVAILABLE`。
