## Purpose

把校招简章做成公司公告目录：一行简章含岗位列表、公告链接和投递入口。产品只导入运营者确认许可的表格，不爬取第三方看板，并据此拆出可供匹配的岗位和投递渠道。

## ADDED Requirements

### Requirement: Announcements are catalogs, not job providers
系统 SHALL 将校招简章存为独立目录记录，包含公司名称、公告标题、城市、岗位列表、公告链接和投递链接或邮箱。简章 MUST 不是岗位 Provider，也 MUST 不替代具体岗位的 JD 结构化。

#### Scenario: List announcements for a signed-in user
- **WHEN** 用户打开简章看板
- **THEN** 系统返回其可见的简章，含公司、岗位、截止日、公告链接和投递入口，而不把简章行本身当作一条可匹配 JD

### Requirement: Shared announcements are visible, private ones are isolated
未指定私有归属的简章 SHALL 作为共享目录对已登录用户可见。指定归属用户的简章 MUST 只对该用户可见。其他用户的私有岗位 MUST 不能被用于匹配或投递。

#### Scenario: Shared catalog is visible
- **WHEN** 运营者导入未指定归属用户的简章
- **THEN** 任意已登录用户都能在看板中看到该公司公告及其拆出的岗位

#### Scenario: Private announcement is hidden from others
- **WHEN** 简章被导入为用户 A 私有
- **THEN** 用户 B 的看板和岗位列表不包含该简章及其拆出岗位

### Requirement: Operator import is dry-run by default and does not scrape
系统 SHALL 提供运营者表格导入（CSV/XLSX）。默认 MUST 只预览统计、不写入。只有显式执行才落库。系统 MUST NOT 提供爬取第三方校招看板或调用其非公开接口的产品能力。仓库随附样例 MUST 是虚构数据。

#### Scenario: Dry-run reports counts without writing
- **WHEN** 运营者对许可表格运行导入且未显式执行
- **THEN** 输出新增/更新/拒绝统计，数据库不新增简章、岗位或渠道

#### Scenario: Execute splits jobs and channels
- **WHEN** 运营者对含公司、两个岗位名和合法投递邮箱的虚构简章显式执行导入
- **THEN** 系统写入一条简章、两条岗位，以及一条邮箱类型投递渠道

### Requirement: Import is idempotent and keeps unsafe channels out
同一简章内容重复导入 MUST 更新已有记录而不是再插一行。投递 URL 或邮箱未通过既有渠道安全校验时，系统 MUST 拒绝写入该渠道，但 MUST 仍保存简章（岗位可写入）。系统 MUST 不把内网、localhost 或非 HTTPS 招聘页当作合法投递入口。

#### Scenario: Repeat import updates the same announcement
- **WHEN** 相同内容的简章被执行导入两次
- **THEN** 简章仍只有一条，第二次结果记为更新而不是新增

#### Scenario: Unsafe apply URL rejects the channel only
- **WHEN** 简章的投递链接指向环回地址或其它不安全主机
- **THEN** 简章被保存，渠道被拒绝，简章不关联渠道

### Requirement: Expired announcements can be hidden without deleting history
看板默认 SHALL 隐藏已过截止日的简章。过期 MUST 不删除历史岗位或已有投递记录。

#### Scenario: Hide expired by default
- **WHEN** 一条简章的截止日早于当前时间，用户按默认筛选查看看板
- **THEN** 该简章不出现在默认列表中，但仍可通过详情或取消隐藏过期查看
