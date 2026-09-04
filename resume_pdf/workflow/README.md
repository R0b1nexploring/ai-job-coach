# 标准简历生成工作流

本目录把 `resume_pdf/resume_self/` 中的本地参考件提炼成可重复执行的生成流程。参考件只用于版式取样并已被 Git 忽略；工作流不会读取、打印或复制其中的完整个人简历内容。

## 默认交付

一次生成固定产出三类文件：

- `output/docx/<name>.docx`：可编辑版本；
- `output/pdf/<name>.pdf`：最终投递版本；
- `output/qa/<name>.qa.json`：仅含页数、尺寸、字体和标记数量，不含简历正文。

模板采用 A4 单页、深蓝灰、三列经历标题、菱形要点和可选证件照。保留参考件的视觉语言，但移除装饰性图标，以提高 ATS 文本解析稳定性。PDF 必须通过以下门槛：

分区顺序固定把“教育背景”放在求职方向之后，其余分区继续保持输入 JSON 中的相对顺序。

1. `content_version=2` 且符合项目结构化简历契约；
2. 可投递版所有要点均 `achieved=true`，并引用 `source_fact_ids`；
3. 蓝图未达成要点必须 `achieved=false`、引用 `source_target_ids`，并在成品中显示 `[未达成 · 学习目标]`；
4. `new_claims` 必须为空，正文不得超过单页预算；
5. PDF 为 A4 单页，所有字体均嵌入并带 Unicode 映射；
6. 每个分区和要点必须存在于 PDF 文本层，便于 ATS 读取。

渲染时会从 `template_profile.json` 的候选列表中选择系统真实安装的中文字体，避免文档声明“微软雅黑”但转换器实际替换成不含中文字形的字体。

## 标准流程

```text
原始简历上传
→ 结构化提取
→ 用户补全与确认事实
→ 导入 JD 并生成匹配报告
→ 创建 capability targets
→ 生成 target 或 submittable 的 content_json
→ Fact Guard 逐条校验
→ 本工作流再次做离线结构校验
→ 生成 DOCX
→ LibreOffice 转 PDF
→ PDF 自动 QA + PNG 人工目检
→ 交付
```

生产输入应来自系统已通过 Fact Guard 的 `ResumeVersion.content_json`。示例文件仅使用虚构人物和虚构经历，不能作为真实事实来源。

## 使用

在仓库根目录执行：

```bash
apps/api/.venv/bin/python -m resume_pdf.workflow.generate \
  --input resume_pdf/workflow/examples/fictional-target.json \
  --name company-role-target
```

加入本地证件照：

```bash
apps/api/.venv/bin/python -m resume_pdf.workflow.generate \
  --input resume_pdf/private/company-role.json \
  --photo resume_pdf/private/portrait.jpg \
  --name company-role-submittable
```

同名文件默认不会被覆盖；确认需要重建时添加 `--force`。`resume_pdf/private/`、`resume_pdf/resume_self/`、`output/` 与 `tmp/` 均被 Git 忽略。

## 两类版本

- `submittable`：仅允许已确认事实，适合正式投递。
- `target`：允许加入尚未完成的学习目标，但必须显式标记。是否投递由用户决定；系统只负责一次性提醒和事实边界可见。

模板参数集中在 `template_profile.json`。修改模板后应重新运行测试并生成虚构示例 PDF，最后检查 `tmp/pdfs/generated/` 中的 PNG。
