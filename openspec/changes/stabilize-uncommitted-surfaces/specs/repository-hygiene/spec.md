## Purpose

规定本仓库可以分发什么、必须忽略什么、以及哪些材料既不能进 Git 也不能写入产品数据库，避免把个人简历、抓取结果和运行时文件混进产品交付。

## ADDED Requirements

### Requirement: Fictional product samples may be committed
仓库 SHALL 只把虚构、可公开的产品样例当作可提交资产，包括虚构校招简章样例、虚构经历范本文案，以及系统默认简历模板的版式参数。演示账号与种子数据 MUST 继续使用彻底虚构的人物与单位。

#### Scenario: Campus sample in the repository is fictional
- **WHEN** 检查仓库中的校招简章样例文件
- **THEN** 其中公司、岗位和联系方式都是虚构示例，而不是第三方看板的原始导出

### Requirement: Runtime, private, and generated files must stay untracked
系统配置的忽略规则 MUST 覆盖本地数据库与上传目录、构建产物、临时渲染输出、个人简历样张目录，以及运营者导入的原始渠道/简章文件目录。这些路径 MUST NOT 被要求提交。

#### Scenario: Personal resume samples are ignored
- **WHEN** 本地存在仅供版式取样的个人 PDF 目录
- **THEN** 版本控制将其视为忽略文件，提交预览中不出现这些 PDF

#### Scenario: Operator import files stay local
- **WHEN** 运营者把许可表格放入渠道导入目录并执行导入
- **THEN** 原始表格不被要求提交，数据库只保存导入后的结构化简章/渠道字段

### Requirement: Scrapes, research dumps, and complete resumes must not ship
仓库 MUST NOT 提交第三方岗位抓取结果、岗位调研长文、完整真实简历正文或证件照。产品数据库 MUST NOT 把上述材料存成模板、范本或种子。公开招聘页读取 MUST 继续走既有白名单 Job Provider，而不是把一次性抓取脚本升级为默认岗位来源。

#### Scenario: Job collection dump is excluded
- **WHEN** 工作区存在从公开招聘接口一次抓取的 JD JSON 或据此生成的分析文档
- **THEN** 这些文件不被纳入产品提交集，也不被种子脚本写入数据库

#### Scenario: Default template seed has no private biography
- **WHEN** 迁移或种子写入系统默认简历模板
- **THEN** 写入内容只有版式参数和虚构示例所需的结构，不含真实姓名、联系方式或完整个人经历

### Requirement: Product code lives in the application tree
简历渲染与模板应用的产品代码 MUST 位于应用后端（及对应测试）之内。仓库根目录 MUST NOT 再作为第二套正式导出入口。本地忽略的样张目录可以保留在开发机器上，但 MUST NOT 作为运行时依赖。

#### Scenario: Export does not read ignored personal PDFs
- **WHEN** 用户在应用中导出一份已审核简历
- **THEN** 渲染只使用数据库中的版本内容、模板快照和可选的用户私有存储文件，不读取被忽略的个人样张目录
