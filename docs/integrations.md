# 外部项目参考与集成说明

## Resume Optimizer

项目设计参考了 [`Liliane0310/Resume-Optimizer`](https://github.com/Liliane0310/Resume-Optimizer) 的 JD 拆解、STAR 改写和单页 HTML 简历思路。对方 README 声明 MIT，但仓库检查时未发现独立 `LICENSE` 文件；正式商业发布前应再次确认授权状态。

本项目没有把 Claude Code Skill 作为运行依赖，也没有直接执行对方脚本。当前采用的是与本系统权限和事实模型结合的独立实现：

- DOCX 解析补充表格文字读取；
- 仅对事实检查和顾问审核均通过的版本提供 HTML 预览/下载；
- HTML 内容统一转义并设置 Content Security Policy；
- 保留 `source_fact_ids`、Fact Guard、用户隔离和顾问分配；
- JD 隐藏偏好只能标记为 AI 推断，不能变成用户事实；
- 不接入虚构雇主、奖项、证书或冒用他人成果的生成逻辑。

后续若加入证件照，不使用本机绝对路径；照片必须经过鉴权上传、随机 Storage Key、格式和大小校验，并只在授权导出时读取。

## 公开岗位页面

第三方岗位信息按来源逐项接入。优先使用 Greenhouse、Lever 等公开接口；其他企业或
ATS 页面仅在管理员确认访问许可并配置域名白名单后，读取标准 `JobPosting`
JSON-LD。系统不保存招聘平台账号、不绕过验证码、不跟随重定向，也不使用通用 DOM
选择器或反爬规避技术。所有入库岗位仍需用户打开原始链接核对。

## 公司投递渠道导入

投递渠道是公司级的招聘页、投递表单或邮箱，不是具体岗位源，也不实现自动投递。产品只提供 CSV/XLSX 导入能力，仓库不附带、不生成种子数据，也不分发任何第三方渠道清单。运营者必须在导入前自行确认数据来源和使用许可；原始文件统一放入被 Git 忽略的 `data/channel-imports/`。

规范字段如下，原始列名可用 `--mapping` 指向这些字段：

| 字段 | 说明 |
|---|---|
| `company_name` | 必填，公司名称 |
| `company_aliases` | 可选，逗号或分号分隔 |
| `channel_type` | `career_page`、`email` 或 `form` |
| `url` / `email` | 按渠道类型填写 |
| `scope` | `campus`、`experienced` 或 `both` |
| `regions` / `industries` | 可选，多值分隔 |
| `source_updated_at` | 来源更新时间，ISO 日期或时间 |
| `notes` | 可选内部说明 |

默认只预览计数，只有 `--execute` 才写入：

```bash
apps/api/.venv/bin/python scripts/import_channels.py \
  data/channel-imports/licensed-channels.xlsx \
  --source licensed_operator_file

apps/api/.venv/bin/python scripts/import_channels.py \
  data/channel-imports/licensed-channels.xlsx \
  --source licensed_operator_file \
  --mapping data/channel-imports/mapping.json \
  --execute
```

脚本只输出新增、更新、跳过、拒绝和拒绝原因计数，不打印公司清单或完整邮箱。重复导入按内容哈希更新，不产生重复行。导入前会拒绝非 HTTPS、IP 字面量、localhost/本地域名、解析到私有或保留网段、带 userinfo、非 443 端口和非法邮箱。

`public_jsonld` 的运行时允许域名是 `JOB_SOURCE_ALLOWED_HOSTS` 与未失效 `career_page` 渠道域名的并集。导入或累计 3 次失效反馈后会立即清除缓存；动态允许域名不会放宽 HTTPS、DNS 公网地址复核、禁止重定向、robots.txt、2MB 上限和 Content-Type 白名单。

全局渠道（`owner_user_id=NULL`）属于公司数据，不随单个用户的保留期清理；用户私有渠道会在该用户数据清理时删除。邮件渠道只生成可复制或通过 `mailto:` 打开的草稿，系统不配置 SMTP、不发送邮件、不自动附加简历，也不提供批量入口。
