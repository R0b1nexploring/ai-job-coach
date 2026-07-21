# 当前 API

启动后访问 <http://localhost:8000/docs> 查看实时 OpenAPI 文档。接口统一使用 `/api` 前缀，错误格式为：

```json
{"error":{"code":"ERROR_CODE","message":"清晰中文提示","details":{},"request_id":"uuid"}}
```

## 单页简历优化

```text
POST /api/coach/optimize
```

请求使用 `multipart/form-data`：

- `resume_file`：DOCX 或文本型 PDF；
- `jd_image`：PNG、JPEG 或 WebP；
- `jd_text`：可选的 JD 补充文字，最长 20,000 字。

接口要求登录。它会在一个请求中完成简历解析、JD 本地 OCR、岗位结构化、简历改写、Fact Guard 和面试引导，并返回：

```json
{
  "job": {},
  "tailored_resume": {},
  "interview_guide": {},
  "ocr_provider": "rapidocr",
  "notices": []
}
```

下载事实检查通过的建议稿：

```text
GET /api/coach/resume-versions/{version_id}/download
```

下载响应使用 `private, no-store`，并在 DOCX 内标注“建议稿，请核对”。

## 账号

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
DELETE /api/account
```

旧版岗位、投递、额度、顾问和管理员 API 为兼容已有本地数据库暂时保留，但不属于当前用户界面或新产品流程。
