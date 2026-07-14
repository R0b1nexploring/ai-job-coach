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
