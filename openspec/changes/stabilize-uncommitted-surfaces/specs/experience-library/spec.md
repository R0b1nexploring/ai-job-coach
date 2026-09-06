## Purpose

把实习和项目经历做成用户可维护的一等材料库，全站虚构范本只供对照；只有用户补全真实组织并确认后，才能进入已确认事实并参与匹配与可投递简历。

## ADDED Requirements

### Requirement: Users can maintain their own internships and projects
系统 SHALL 允许已登录用户新增、查看、编辑和删除自己的实习与项目经历。每条经历 MUST 包含类型（实习或项目）和标题。用户 MUST 只能看到自己的经历以及全站范本，不能看到其他用户的经历。

#### Scenario: Create an internship
- **WHEN** 用户提交类型为实习、含标题、真实组织名称和经历说明的新记录
- **THEN** 系统保存该经历为该用户所有，并把它写入该用户经历库中的已确认事实（provenance 为用户补充）

#### Scenario: Isolation between users
- **WHEN** 用户 A 已保存一条自己的经历，用户 B 请求经历列表
- **THEN** 用户 B 的自有经历列表不包含用户 A 的记录，且用户 B 无法编辑或删除用户 A 的记录

### Requirement: System templates are read-only contrasts
系统 SHALL 提供全站虚构实习/项目范本。范本 MUST 不属于任何用户。用户 MUST 不能直接编辑或删除范本。从范本创建的副本 MUST 清空组织名称和经历正文，且 MUST 不立即变成已确认事实。

#### Scenario: Copy a template
- **WHEN** 用户按范本创建一条经历
- **THEN** 新记录属于该用户，组织名称为空，且未链接为已确认事实

#### Scenario: Template cannot be patched
- **WHEN** 用户请求修改一条全站范本
- **THEN** 系统拒绝该请求

### Requirement: Confirming an experience requires real, non-template facts
系统 MUST 在用户确认经历加入事实库之前，要求真实组织名称以及摘要或要点至少一项。若组织名称仍是范本中的虚构单位，系统 MUST 拒绝确认。

#### Scenario: Confirm blocked while still using template organization
- **WHEN** 用户把范本副本的组织名称改回范本虚构单位并请求确认
- **THEN** 系统返回可理解的错误，且不创建或确认对应事实

#### Scenario: Confirm succeeds with the user's own organization
- **WHEN** 用户填写自己的真实组织名称和经历说明后确认
- **THEN** 该经历链接到 provenance 为用户补充、状态为已确认的事实，并可供后续匹配与简历生成使用

### Requirement: Confirmed resume facts sync into the experience library
当用户在上传简历中确认实习或项目类事实时，系统 SHALL 在经历库中为该用户建立或关联对应记录，来源标记为原始简历。系统 MUST 不把范本当成这些事实的来源。

#### Scenario: Confirmed employment fact appears in the library
- **WHEN** 用户确认一份上传简历中的工作/实习事实
- **THEN** 经历库出现对应的自有实习记录，并关联到该已确认事实

### Requirement: Experience data is personal and must be purged with the account
删除或清理用户账号时，系统 MUST 删除该用户的自有经历记录。全站范本 MUST 保留。

#### Scenario: Account purge removes owned entries only
- **WHEN** 管理员执行某用户的不可逆清理
- **THEN** 该用户的经历记录被删除，全站范本仍然存在
