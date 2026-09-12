> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

简历工作台把目标输入、真实素材补全、双版本生成、质量解释、编辑、导出和面试指南组织为一个连续自助流程，让不同年级的理工科用户使用同一套产品路径。

## ADDED Requirements

### Requirement: A4 preview scales without clipping
工作台 MUST 按容器尺寸等比显示完整 210×297mm 页面，正确区分 CSS px 与 PDF pt。预览缩放 MUST NOT 改变打印布局或正文。验收 SHALL 覆盖桌面和窄屏，检查完整页面与文字显示，不能仅断言 iframe 存在。

#### Scenario: A4 page is shown in a narrow container
- **WHEN** 预览容器小于 A4 页面原始 CSS 宽度
- **THEN** 页面等比缩小并保留完整边界，不因固定 595px 容器裁切 210mm 页面；打印仍使用原始 A4 尺寸

### Requirement: The studio is the default user journey
普通用户 SHALL 从统一简历工作台完成目标画像、上传或空白建档、素材追问、双轨生成、版本对比、导出和指南查看。系统 MUST NOT 根据年级或毕业年份切换流程。

#### Scenario: A first-year and final-year user enter the studio
- **WHEN** 两名毕业年份不同的用户打开工作台
- **THEN** 两人看到相同流程，并由各自材料和 JD 决定输出内容

### Requirement: The studio progressively discloses optional input
工作台 SHALL 默认只展示 JD 输入和生成主操作。单 JD 的保存与画像创建 SHALL 由一次操作完成。历史岗位、已有画像、已保存素材和多 JD 合并不得以长列表占据默认流程；补充经历仅在用户主动展开后显示，并使用组织、自然语言描述和可选结果三个易懂输入。

#### Scenario: A new user opens the studio
- **WHEN** 新用户尚未主动补充经历或选择历史数据
- **THEN** 页面不显示岗位复选框列表、画像单选框列表或专业素材字段，并允许用户从粘贴 JD 直接进入生成

#### Scenario: A user chooses to add experience
- **WHEN** 用户点击“补充一段经历”
- **THEN** 页面显示三个有示例说明的输入，并在保存后收起表单，将经历直接加入生成参考

### Requirement: Users can inspect and control every visible bullet
用户编辑、锁定、局部重生成、排序、撤销和版本对比为未来 TODO，本轮不新增或完善；已有功能保留兼容。以下交互合同在恢复该功能开发时执行，本轮仅复用预览、下载与指南查看。

工作台 SHALL 提供 A4 预览、真实版与蓝图对比、逐 bullet 来源、质量问题、锁定、局部重生成、排序、撤销和版本对比。用户操作后 MUST 看到重新校验状态。

#### Scenario: Lock a strong bullet before regeneration
- **WHEN** 用户锁定一个要点并重生成整份简历
- **THEN** 锁定要点保持不变，其余内容可更新，质量报告同步刷新

### Requirement: Automatic delivery does not require advisor approval
内容硬门禁通过的 ready 或 degraded 版本 SHALL 可由所有者直接预览，不要求顾问批准；各格式 SHALL 在自身文件门禁通过后独立交付，PDF 故障不得阻止内容预览或其他合格格式。缺少已确认事实不得阻止 v3 AI 扩写交付。degraded 版本 MUST 在工作台显示质量降级提示。

#### Scenario: Export a ready self-service resume
- **WHEN** 用户的版本通过自动门禁但从未提交顾问审核
- **THEN** 用户仍可下载 HTML、DOCX 和可用的 PDF

### Requirement: Non-core features leave the primary navigation
普通用户主导航 SHALL 以简历工作台、面试指南和账户设置为主。岗位看板、投递管理、学习目标、顾问运营和套餐额度不得出现在新的主流程，但旧 URL 与已授权接口保持兼容。

#### Scenario: Existing bookmarked legacy page is opened
- **WHEN** 有权限的用户直接访问保留的旧 URL
- **THEN** 页面继续工作，但不会把用户从新工作台主流程自动引向该页面

### Requirement: Private input and generation state are recoverable
工作台 SHALL 保存草稿与异步生成状态，刷新页面后可继续查看；错误信息不得包含完整简历、JD、照片或模型 prompt。

#### Scenario: Refresh while a bundle is generating
- **WHEN** 用户在异步生成期间刷新页面
- **THEN** 工作台从服务端恢复同一 bundle 的进度，不发起重复生成

### Requirement: Invite trial access and task feedback are recoverable
邀请试用建设为后续规划，本轮不主动实施；已有恢复和权限行为保持兼容。

小范围真实用户试用 SHALL 使用单次、限时邀请码注册，并显示剩余 AI 额度。工作台 MUST 分别展示任务的 queued、running、succeeded、degraded 和 failed 状态、当前阶段、可公开错误及可用重试入口。草稿保存、简历生成、指南和导出 MUST 分别反馈状态，一个交付物失败不得使已完成的其他交付物失效。

#### Scenario: Invite is consumed concurrently
- **WHEN** 两个注册请求同时核销同一个单次邀请码
- **THEN** 只有一个请求创建账号，另一个收到邀请码已失效错误

#### Scenario: PDF fails after resumes are ready
- **WHEN** 两份简历已完成但 PDF 转换或物理检查失败
- **THEN** 用户仍可查看简历和下载可用格式，并只重试 PDF 任务

#### Scenario: Editing from two browser tabs conflicts
- **WHEN** 一个标签页基于旧内容版本保存修改
- **THEN** 系统返回 `409 VERSION_CONFLICT`，页面保留当前输入并提示刷新合并

#### Scenario: Session expires while polling
- **WHEN** 用户等待任务时登录状态过期
- **THEN** 页面保留当前任务上下文，重新登录后恢复查询同一任务
