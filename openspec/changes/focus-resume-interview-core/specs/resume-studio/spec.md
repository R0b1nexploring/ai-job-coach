> **当前范围（2026-09-18）**：完整业务路线按主计划顶部 R0–R6 与 tasks 第17节执行。恢复最小邀请试用、持久任务与真实文件验收；旧“上线暂缓”范围被覆盖，固定规模实验、原型库及完整编辑器仍延期。历史实现勾选不代表新增合同已验收。

> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

简历工作台把目标输入、真实素材补全、双版本生成、编辑、导出和面试指南组织为一个连续自助流程，让不同年级的理工科用户使用同一套产品路径。

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

工作台 SHALL 提供 A4 预览、真实版与蓝图对比、逐 bullet 来源、锁定、局部重生成、排序、撤销和版本对比。用户操作后 MUST 看到简洁处理状态，不展示内部质量诊断。

#### Scenario: Lock a strong bullet before regeneration
- **WHEN** 用户锁定一个要点并重生成整份简历
- **THEN** 锁定要点保持不变，其余内容可更新，质量报告同步刷新

### Requirement: Automatic delivery does not require advisor approval
内容硬门禁通过的 ready 或 degraded 版本 SHALL 可由所有者直接预览，不要求顾问批准；各格式 SHALL 在自身文件门禁通过后独立交付，PDF 故障不得阻止内容预览或其他合格格式。缺少已确认事实不得阻止 v3 AI 扩写交付。degraded 机器状态 MUST 保留，工作台按下述简洁反馈合同展示，不显示质量降级技术提示。

#### Scenario: Export a ready self-service resume
- **WHEN** 用户的版本通过自动门禁但从未提交顾问审核
- **THEN** 用户仍可下载 HTML、DOCX 和可用的 PDF

### Requirement: Generation diagnostics stay out of the user interface
系统 SHALL 在后台完成 STAR 检查、模型评审及定向修复。主界面 MUST 以成稿为中心，不展示 critic 评分、STAR 诊断、模型协议错误、degraded 标识或内部修复过程，也不要求用户理解或处理这些问题。机器可读状态与内部诊断 MUST 保留供开发者排查，本要求不新增开发者页面。失败时 SHALL 仅提供简短中文说明和重试入口，例如“本次未能生成完整简历，请重试。”蓝图未达成项的 `*` 及解释 MUST 继续保留；隐藏技术诊断不改变事实来源状态。

#### Scenario: A partial critique permits degraded delivery
- **WHEN** 内容合格但 critic 缺项，版本内部状态为 degraded
- **THEN** 用户看到可用成稿，不看到缺失维度、评分或降级技术提示，开发者仍可追溯原因

#### Scenario: Background repair cannot produce valid content
- **WHEN** 修复与回退均未满足交付合同
- **THEN** 页面不展示不合格候选成稿，只显示简短中文失败说明与重试入口，不暴露模型错误或问题清单

#### Scenario: A blueprint is successfully delivered
- **WHEN** 后台修复完成且蓝图内容可交付
- **THEN** 页面显示成稿与未达成项的星号说明，不显示修复轮次、评分或 STAR 诊断


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
邀请试用已恢复到当前R3–R6路线；本要求与新增注册/额度/恢复合同共同实施。

小范围真实用户试用 SHALL 使用单次、限时邀请码注册，并显示剩余 AI 额度。工作台 MUST 将任务机器状态映射为简洁中文反馈：queued/running 显示等待或生成中，succeeded/ready/degraded 展示可用结果，failed 显示简短失败说明与重试入口；不直接展示状态码、内部阶段或技术错误。草稿保存、简历生成、指南和导出 MUST 分别反馈状态，一个交付物失败不得使已完成的其他交付物失效。

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

### Requirement: Invited users receive usable trial access without manual intervention
系统 SHALL 支持管理员创建/撤销默认单次、7天有效的邀请码，只保存邀请码哈希。用户注册时 MUST 在同一事务内核销邀请码、创建用户与资料并发放5次双版本额度；生产 MUST NOT 依赖demo账号或注册后管理员人工grant。默认其他AI操作每日20次，内部修复及自动两指南不重复计费。额度不足 SHALL 显示试用额度用完及联系管理员提示，不出现未实现支付入口。管理操作 MUST 校验管理员角色。

#### Scenario: A new invited user registers and generates
- **WHEN** 用户持有效邀请码自行注册并提供有效JD
- **THEN** 用户获得5次额度并能直接提交生成，无需管理员中途干预或上传旧简历

#### Scenario: Two users redeem one invitation concurrently
- **WHEN** 两个注册事务同时提交同一单次邀请码
- **THEN** 仅一个用户注册并得到一次初始额度，失败事务不留下部分用户或额度；过期/撤销邀请码不可使用

### Requirement: Saved inputs and work survive interrupted sessions
工作台 SHALL 对输入停止800ms后自动保存并显示简洁状态，更新携带资源revision；过期写入 MUST 返回409 VERSION_CONFLICT且保留页面当前文本。刷新或重新登录 SHALL 从服务器恢复已保存草稿、任务和交付物。网络超时 MUST 用原幂等键查询或重放，不能创建重复生成。未保存文本只保证当前页面内存保留，不将完整材料写入URL或浏览器持久存储。

#### Scenario: A save conflicts with another tab
- **WHEN** 两个标签页基于同一revision修改素材，第二次提交已过期
- **THEN** 第二次写入被拒绝，页面保留当前文本并提供刷新合并，不能静默覆盖服务器内容

#### Scenario: Session expires during generation
- **WHEN** 用户生成途中登录过期并重新登录
- **THEN** 任务继续执行，页面找回同一任务与已保存内容，不重复扣额度或发起新生成

### Requirement: Production access is protected and recoverable
邀请试用 MUST 使用HTTPS同域、安全HttpOnly Cookie、精确Origin与CSRF写请求校验，并提供跨API进程共享的登录/注册限流。默认每账号15分钟10次失败登录、每IP15分钟50次失败登录、每IP每小时10次注册，允许部署调整。系统 MUST 拒绝跨账号任务与文件访问，不向浏览器或日志暴露模型prompt、完整材料、claim token或密钥。

#### Scenario: A write comes from an untrusted origin
- **WHEN** 写请求携带有效会话但Origin不匹配或缺少有效CSRF token
- **THEN** 请求被拒绝且不改变数据，不能仅因CORS配置或Cookie存在而放行

#### Scenario: Login attempts exceed the shared limit
- **WHEN** 请求分布到多个API进程后累计超过登录失败阈值
- **THEN** 系统返回429和Retry-After，不因切换进程绕过限制

### Requirement: Trial delivery requires deployment evidence
系统 SHALL 在Linux生产配置下验证HTTPS、PostgreSQL、私有存储、固定Chromium、任务恢复和备份恢复，才能开放首批邀请。WSL启动、mock通过或文档完成 MUST NOT 被声明为生产上线完成。默认每日加密备份、14天保留，恢复目标RPO24小时/RTO4小时 SHALL 以演练记录验证；恢复后 MUST 应用删除清单，避免已删除用户数据重新对外可用。

#### Scenario: Production storage is unavailable
- **WHEN** 生产配置或私有存储依赖缺失
- **THEN** 预检失败或相关操作明确失败，不切换development或本地存储宣称部署成功

#### Scenario: Restore a backup containing a deleted account
- **WHEN** 运维在隔离环境恢复旧备份
- **THEN** 对外恢复服务前重放删除清单并验证数据库与对象一致性，记录恢复点及耗时
