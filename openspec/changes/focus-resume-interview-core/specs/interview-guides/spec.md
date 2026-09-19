> **当前范围（2026-09-18）**：完整业务路线按主计划顶部 R0–R6 与 tasks 第17节执行。恢复最小邀请试用、持久任务与真实文件验收；旧“上线暂缓”范围被覆盖，固定规模实验、原型库及完整编辑器仍延期。历史实现勾选不代表新增合同已验收。

> **2026-09-05 用户最新裁决：允许 AI 扩写。** 新生成的工作台 v3 简历采用 `factuality_policy=ai_expansion`，允许超出已确认事实补充内容，也允许仅凭目标画像创建草稿。缺少事实支持、新主张和未达成状态不再阻止生成、预览或导出；来源 ID 归属、结构及版面仍需通过检查。AI 补充记录 `verification_status=ai_generated`、`achieved=false` 作为内部来源状态，但在工作台、导出和指南不显示“待核验”标记，不自动写入已确认事实库。`submittable` 的界面名称改为“求职版”。本裁决覆盖本文此前相冲突的事实限制；旧 v1/v2 接口保持兼容。

## Purpose

面试指南能力为真实能力简历和蓝图 Plus 分别生成与每个可见要点严格绑定的准备材料，让用户知道如何证明真实经历，以及哪些未来目标目前不能冒充已完成。

## ADDED Requirements

### Requirement: Guides expand saved internal plans without inventing another project
指南 SHALL 使用其绑定版本实际保存的项目方案和可见正文，将具体方法、取舍、难点及验证方式转为准备问题和回答要点。系统 MUST NOT 为了让指南看似完整而另编角色、技术路线或已取得成果。内部方案不是独立项目教程；既有指南中的针对性实践准备继续保留。求职版只消费其实际正文和对应来源/方案，不直接套用蓝图方案中的未来成果。

#### Scenario: The saved plan contains an unresolved design assumption
- **WHEN** 方案中的某个方法或指标尚待验证
- **THEN** 指南将其作为需要理解或验证的问题，说明应准备的材料，不生成冒充已经实施的第一人称答案

#### Scenario: Only the internal plan changes
- **WHEN** 保存的项目方法、角色、目标或验证方式改变，而简历短句尚未改变
- **THEN** 系统更新语义内容哈希并使原指南过期，新指南读取新方案，不能沿用旧方案生成的内容

### Requirement: Project guides explain the same STAR story in depth
蓝图指南 MUST 为每个项目提供与已保存 STAR 说明和正文一致的项目讲解：问题背景、本人任务、行动过程与取舍、结果验证。指南 SHALL 组织项目级主线并关联逐条要点，避免把同一段通用介绍重复到所有卡片。求职版指南 SHALL 以其实际正文和来源为依据，不借用蓝图中的未来成果。

#### Scenario: A project uses a particular method
- **WHEN** 简历项目描述为解决某问题选择了具体方法或工具
- **THEN** 指南围绕为什么选它、怎样实施、遇到什么难点、如何验证展开连续追问，并给出回答要点、追问意图、所需证据与常见误区

#### Scenario: A result is a proposed performance target
- **WHEN** 蓝图项目结果包含尚未验证的性能目标
- **THEN** 指南解释应如何定义指标、设置条件和验证结果，把缺失实验列为实践准备，不编造已完成的测量、数值或第一人称经历

#### Scenario: User needs to prepare an uncompleted project
- **WHEN** 用户查看尚未完成的蓝图项目指南
- **THEN** 指南给出关键知识、可执行实践步骤、应形成的材料和当前诚实表达边界，而不是只提示风险或提供通用问题

### Requirement: Guide quality includes project consistency and specific questions
指南 MUST 同时覆盖全部可见要点及蓝图项目主线，拒绝跨项目卡片、相互矛盾的角色/方法/结果和重复卡片冒充覆盖。覆盖齐全不等于内容优质；问题与回答要点 SHALL 对应具体项目细节。模型输出缺项后由规则补齐或使用模板回退时，系统 MUST 说明实际降级来源，不将混合或通用内容冒充完整模型评审结果。

#### Scenario: Cards cover every ID but repeat generic questions
- **WHEN** 指南每个要点都有卡片，却仅重复“你做了什么、结果如何”
- **THEN** 质量报告指出缺少项目针对性，不以 ID 覆盖齐全证明指南质量，不填充虚假模型评分

#### Scenario: An old resume lacks structured STAR context
- **WHEN** 用户查看没有项目说明扩展的旧版简历指南
- **THEN** 系统使用旧正文及其有效来源，把未知项目细节列为准备问题，不改写旧简历或补造本人事实

### Requirement: Every resume bundle receives two version-bound guides
系统 SHALL 在两版内容门禁通过、bundle 进入 ready 或可交付 degraded 后，为求职版和蓝图 Plus 分别自动排队生成指南，不等待 PDF 成功，也不要求用户打开指南才开始生成。每份指南 MUST 绑定具体 resume version、目标画像和内容哈希，不得使用同一份泛化指南替代。指南任务的失败 MUST NOT 使已完成的简历失效。

#### Scenario: Resume bundle becomes ready
- **WHEN** 双轨简历通过内容门禁并进入 ready 或可交付 degraded
- **THEN** 系统为两个版本分别排队生成指南，并在 bundle 中返回指南状态

#### Scenario: PDF is unavailable after content delivery
- **WHEN** 两版内容已可交付，但 PDF 转换失败
- **THEN** 两份指南仍可独立生成，PDF 失败不取消指南任务

### Requirement: The submittable guide covers every visible claim
真实能力版指南 MUST 为简历中每个可见 bullet 生成来源绑定的 claim card，包含主问题、连续追问、六段式讲法、个人贡献边界、核验材料和危险说法；并 SHALL 提供 60/90 秒自我介绍、JD 专业与行为题、岗位动机、反问清单和面试前检查表。

#### Scenario: Generate a guide for three resume bullets
- **WHEN** 求职版含三个均有已确认事实支持的可见 bullet
- **THEN** 指南恰好覆盖三个 bullet id，且每张卡引用该 bullet 的事实来源

### Requirement: The blueprint guide exposes every future-item risk
蓝图指南 MUST 覆盖每个 `achieved:false` 要点，列出可能被问穿的问题、当前能够诚实回答的边界、缺少的证据和完成后应具备的答法。系统 MUST NOT 生成把未完成内容描述为已完成的回答。

#### Scenario: Blueprint contains an unearned award target
- **WHEN** 蓝图含一项尚未取得的奖项目标
- **THEN** 指南明确其未达成状态、当前不可声称拥有，并列出未来需要的核验证据

### Requirement: Guide coverage and grounding are hard gates
每张卡 MUST 引用绑定版本中的 bullet id，可见 bullet 覆盖率 MUST 为 100%。事实型卡片 MUST 引用该 bullet 的实际事实来源；未确认素材与 AI 扩写卡 SHALL 使用实际存在的素材或目标引用，不强求不存在的事实 ID。无事实来源的扩写 MUST 保留未确认语义，不得伪造来源或将内容描述为已验证经历；指南也不得新增简历与来源之外的用户事实。非法来源、错误状态或漏项 MUST 阻止指南进入 ready，而缺少已确认事实本身不得阻止为 AI 扩写生成准备指南。

#### Scenario: An AI-expanded bullet has no confirmed fact
- **WHEN** 求职版包含没有已确认事实支持的 AI 扩写要点
- **THEN** 指南绑定该 bullet，提供诚实表达边界与需补充的证据，不伪造事实 ID、不把扩写当作已完成经历，也不显示“待核验”标签

#### Scenario: Model omits one resume bullet
- **WHEN** 生成结果没有覆盖绑定版本中的一个可见 bullet
- **THEN** 系统触发修复或安全回退，并在补齐前不把指南标为 ready

### Requirement: Guides become stale after resume changes
当绑定简历内容哈希变化时，现有指南 MUST 标为 stale，并 SHALL 保留为历史记录直到新指南生成完成。

#### Scenario: User edits a resume bullet
- **WHEN** 用户保存对已有关联指南的简历修改
- **THEN** 旧指南立即显示过期，新指南必须基于新内容哈希生成

### Requirement: First release delivers guides without practice workflows
第一阶段 SHALL 只提供指南查看和导出，不提供文字作答、自动评分、顾问评分或语音模拟入口；旧 Interview 功能保持兼容但不得混入新指南合同。

#### Scenario: User opens a new interview guide
- **WHEN** 用户查看新生成的指南
- **THEN** 页面展示准备内容而不要求填写答案、提交评分或预约顾问

### Requirement: Guide tasks are durable and independent of resume workers
系统 MUST 将双版本可交付结果与两份指南任务在同一数据库事务内持久化，以所有者、简历版本、目标快照、语义哈希和指南类型绑定输入，并通过数据库唯一性避免自动重复排队。父任务 MUST 在保存结果及排队后结束，不等待指南调用；指南 SHALL 使用独立消费者与同一数据库，可复用同一 worker 程序，无需 Redis/Celery。指南任务 MUST 独立领取、续租、重试并校验 claim token 及当前哈希。历史已可交付但缺任务的版本 SHALL 幂等补排，旧哈希结果 MUST NOT 覆盖当前指南。

自动两份指南 SHALL 包含在父生成操作额度中，恢复和重放不额外扣费；用户主动重生成按其他 AI 操作规则结算。queued 子任务 MUST 允许同时保存，执行仍遵守每用户并发上限。单份指南失败 MUST NOT 重生成简历或影响另一份指南。内部故障诊断 MUST 保留且不展示在主界面。

#### Scenario: Worker exits immediately after saving resumes
- **WHEN** 双版本与指南排队事务提交后，简历 worker 立即退出
- **THEN** 独立指南消费者仍从持久队列生成两份指南，不依赖页面打开或重新生成简历

#### Scenario: One guide needs a retry
- **WHEN** 一份指南失败或运行中断而另一份已完成
- **THEN** 系统仅恢复或重试该指南，保留已完成交付物，自动恢复不重复扣费

#### Scenario: Old guide finishes after a content change
- **WHEN** 指南任务完成时其绑定内容哈希已过期
- **THEN** 提交不能覆盖新哈希指南或成为当前可用结果，按历史过期结果处理

#### Scenario: Automatic enqueue is replayed
- **WHEN** 并发请求或补排重复处理同一版本、哈希及指南类型
- **THEN** 数据库约束保证复用同一自动任务，不重复生成交付记录或扣除额度

### Requirement: Preparation stays within the saved resource boundary
指南 MUST 继承项目已保存的资源、数据与个人贡献边界，不得为了补全讲解新增实验、专业仿真过程或结果。无实验室条件的项目 SHALL 提供可使用已有资料与普通电脑执行的准备步骤；需要但尚未具备的岗位能力保持缺口，不伪造项目填满。真实已提供的实验/仿真经历可围绕其实际过程追问，不因本科身份回避技术深度。

#### Scenario: A selection report is expanded into an interview guide
- **WHEN** 简历项目是基于公开材料参数的选型报告
- **THEN** 指南围绕参数来源、约束、比较方法和选择依据展开，不新增样品制备、显微表征或本人性能实验

### Requirement: Guide questions follow the adopted writing angle
指南 SHALL 使用版本保存的策略、实际正文与项目方案，针对所采用的能力证据组织个人动作、选择理由和产物验证的追问。系统 MUST NOT 独立重选岗位方向或加入正文未采用的成果。历史无策略版本继续使用正文与来源。

#### Scenario: One experience is framed differently for two roles
- **WHEN** 同一素材在两份岗位版本中分别突出设计约束和工序规划
- **THEN** 对应指南分别围绕实际表达重点展开，不复用同一组泛化问答，不补造工厂或实验验证
