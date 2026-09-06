## 1. 仓库卫生

- [ ] 1.1 提交 `.gitignore`：覆盖 `tmp/`、`output/`、`resume_pdf/resume_self/`、`resume_pdf/private/`，并确认 `git status` 不列出个人 PDF、`var/`、渠道原始导入文件
- [ ] 1.2 确保 `data/jd_collection.json`、`data/job_intelligence_analysis.md` 与 `scripts/fetch_job_jds.py` 不进入产品提交集（忽略或移出仓库跟踪），并用 `git check-ignore` 或 `git status` 验证

## 2. 经历库

- [ ] 2.1 完成 `0008` 中 `experience_entries` 部分（若工作区已有则对照 spec 收敛字段），跑 `alembic upgrade head` 与 `test_migrations.py` 确认空库可升级
- [ ] 2.2 落地经历 API（列表/创建/范本复制/更新/确认/删除）与用户隔离，跑 `test_experience_library.py` 全部通过
- [ ] 2.3 确认路径：自建完整经历写入 `user_added` 已确认事实；范本副本清空组织且确认拒绝虚构单位。用该测试文件中的对应用例验证
- [ ] 2.4 上传简历中已确认的实习/项目回写经历库，生成简历读取「选中简历事实 ∪ 经历库事实」。用集成测试或经历库测试验证
- [ ] 2.5 账号清理删除用户自有经历、保留全站范本。扩展隐私测试并确认通过
- [ ] 2.6 前端经历页可列出范本与自有经历、从范本复制、补全后确认。跑相关前端组件测试

## 3. 校招简章

- [ ] 3.1 完成 `0008` 中 `campus_announcements` 及岗位 `announcement_id`/`owner_user_id`，迁移测试覆盖升级与降级
- [ ] 3.2 落地 `scripts/import_jobs.py`：默认 dry-run、`--execute` 拆出简章/岗位/渠道、重复导入幂等。跑 `test_job_import.py`
- [ ] 3.3 不安全投递入口拒绝渠道但保留简章。用现有「环回地址」用例验证
- [ ] 3.4 简章看板 API：共享可见、私有隔离、默认隐藏过期。补测试并确认通过
- [ ] 3.5 岗位可见性走共享/私有规则，匹配不能引用不可见岗位。跑岗位/匹配相关测试
- [ ] 3.6 前端岗位页改为简章看板（公司、岗位、截止日、公告链接、投递入口）。跑 `features.test.tsx` 与主流程 e2e 中受影响断言
- [ ] 3.7 种子只导入 `data/samples/campus_announcements.csv` 虚构样例。跑 `seed_demo.py` dry 路径或导入测试确认无真实第三方数据

## 4. 简历模板进库

- [ ] 4.1 新增 Alembic `0009`：`resume_templates` 表，`resume_versions.template_id` 与 `template_snapshot_json`，插入 `classic-navy-ats-v1` 默认行。空库 `upgrade head` 后能查到该模板
- [ ] 4.2 默认 `profile_json` 只含版式参数（由现有 `template_profile.json` 迁入），测试断言其中无真实姓名、联系方式或完整个人经历
- [ ] 4.3 生成简历版本时写入 `template_id` 与快照；首次导出存量版本时回落默认模板并补快照。用生成/导出测试验证
- [ ] 4.4 修改目录中的默认模板颜色后，旧版本再次导出仍使用快照颜色。新增回归测试并确认通过

## 5. 统一导出并搬走旁路目录

- [ ] 5.1 主应用 HTML/DOCX 渲染改为读取版本快照（无快照则默认模板），不再依赖模块级写死样式作为唯一来源。`test_resume_exports.py` 通过
- [ ] 5.2 蓝图未达成要点在 HTML 与 DOCX 中可见；可投递版本仍只含已确认事实。`test_resume_generation_v2.py` 与导出测试通过
- [ ] 5.3 HTML 与 DOCX 对同一版本的章节数、要点数、未达成标记次数一致。现有一致性测试保持通过
- [ ] 5.4 PDF 导出作为可选路径：有转换器时用同一快照；无转换器时返回明确错误且不阻断 HTML/DOCX。用测试或本地无转换器断言验证
- [ ] 5.5 证件照仅来自用户私有存储；无照片仍能导出。测试覆盖无照片路径
- [ ] 5.6 将 `resume_pdf/workflow` 的产品代码并入 `apps/api`，应用导出不再读取 `resume_pdf/resume_self/`。用测试或路径断言验证运行时不依赖该目录
- [ ] 5.7 删除或停止根目录 `resume_pdf/` 作为正式入口（保留被忽略的本地样张目录即可）。确认 README 与启动文档不再把它列为产品导出命令

## 6. 文档与总验证

- [ ] 6.1 更新 `docs/api.md`、`README.md`、`docs/product-spec.md`、`PROJECT_SPEC.md` §27.6，使其与经历库、简章导入、模板快照一致。人工对照 spec 场景无矛盾
- [ ] 6.2 跑后端相关测试、前端组件测试与主流程 e2e，确认经历、简章、导出、隐私无回归
- [ ] 6.3 确认 Git 状态中无个人 PDF、JD dump、分析报告、`var/` 或渠道原始文件
