# AI 简历教练

一个本地可运行的单页简历优化工具：上传 DOCX 或文本型 PDF 简历，再上传目标岗位 JD 截图，即可在同一页面得到事实受控的定制简历建议稿和面试引导。

当前产品不提供岗位爬取、代投、投递看板、套餐、支付、顾问工作台或管理员运营界面。完整要求见 [`PROJECT_SPEC.md`](PROJECT_SPEC.md)。

## 核心能力

- DOCX（包含表格）和文本型 PDF 简历解析；
- PNG、JPG、WebP 岗位截图本地中文 OCR；
- OCR 失败时使用用户补充的 JD 文字安全回退；
- 基于原简历来源重排和压缩内容；
- Fact Guard 拦截原简历中不存在的数字、工具、证书和成果；
- 约 90 秒自我介绍、重点问题、项目追问和面试准备清单；
- Fact Guard 通过后下载 DOCX 建议稿；
- 默认 Mock LLM，本地可重复测试，不需要第三方密钥。

OCR 使用本地 RapidOCR，JD 截图不会上传到第三方。AI、OCR 和规则提取内容均为待用户核对的建议，不作为已验证事实。

## 环境

- 推荐 Windows 11 + WSL2 Ubuntu；
- Python 3.12+；
- Node.js 18+、npm 9+；
- 仓库建议放在 Linux 文件系统，例如 `~/projects/ai-job-coach`。

## 启动

```bash
cp .env.example .env
./scripts/dev.sh
```

浏览器访问：

- Web：<http://localhost:5173>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health>

脚本会安装依赖、执行 Alembic 迁移、准备虚构 Demo 数据并启动前后端。

## Demo 登录

```text
邮箱：user@example.test
密码：ChangeMe123!
```

以上账号和数据仅用于本地测试。

## 测试

```bash
./scripts/test.sh
```

测试包含后端、前端组件和 Playwright 单页主流程。首次运行浏览器测试时执行：

```bash
cd apps/web
npx playwright install chromium
```

生产构建：

```bash
cd apps/web
npm run build
```

## 真实模型

默认配置：

```text
LLM_PROVIDER=mock
```

如需使用兼容 Chat Completions 的模型，在 `.env` 中配置 `LLM_PROVIDER=compatible`、`LLM_API_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。配置缺失、超时或返回结构无效时会安全回退 Mock；Fact Guard 始终在本地运行。

不得在代码、日志或提交记录中保存密钥和完整真实简历。

## 数据与边界

- 原始简历存放在 Git 忽略的本地私有目录 `var/`；
- JD 截图仅在请求期间处理，默认不持久化；
- 扫描版简历 PDF 暂不支持 OCR；
- 输出是建议稿，使用前必须由用户本人核对；
- 系统不自动登录招聘网站、不处理验证码、不代替用户投递。

生产环境需要 HTTPS、PostgreSQL、私有对象存储、密钥管理、备份与监控。本地开发服务不应直接暴露到公网。
