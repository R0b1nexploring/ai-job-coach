# Windows、WSL 到 Mac 的项目迁移手册

> 编写日期：2026-07-25
> 目标：用私有 GitHub 仓库迁移代码，用独立安全通道迁移密钥和本地数据，最终让 Mac 成为主要开发环境。

## 1. 推荐方案

总体思路是对的，但不要把所有项目直接复制到一个大仓库，也不要在每个目录中执行 `git add .`。

推荐使用下面的迁移结构：

```text
Windows 原生项目 ─┐
                  ├─ 每个项目一个私有 GitHub 仓库 ─→ Mac 克隆、安装依赖、运行测试
WSL Git 项目 ─────┘

.env、密钥、真实简历、数据库、上传文件
                  └─ 密码管理器或加密存储 ─────────→ Mac 本地恢复
```

核心规则：

1. 一个独立产品通常对应一个仓库；只有本来就共同发布的前后端才放在同一个 monorepo。
2. Git 只迁移源码、测试、迁移脚本、依赖锁文件和必要文档。
3. `.env`、API Key、真实简历、数据库、模型文件、构建产物和虚拟环境不进入 Git。
4. Windows/WSL 先推送，GitHub 上确认完整后，Mac 再克隆。
5. Mac 验收通过前不删除 Windows 或 WSL 中的原目录。
6. 迁移期间一个项目只在一台机器上修改，避免两台电脑同时产生未提交改动。

## 2. 当前“AI 简历教练”项目的已核实状态

项目位置：

```text
/home/codex/projects/ai-job-coach
```

GitHub 远端：

```text
https://github.com/R0b1nexploring/ai-job-coach.git
```

2026-07-25 检查结果：

- GitHub 仓库可见性为 `private`，默认分支为 `main`；
- 当前分支是 `main`；
- 本地 `main` 比 `origin/main` 多 1 个提交；
- 工作区还有多项未提交和未跟踪文件；
- `.env`、`var/`、数据库、虚拟环境和 `node_modules` 已在 `.gitignore` 中；
- `.qoder/`、根目录截图以及部分临时脚本目前没有被忽略；
- 未跟踪的 `.qoder/settings.local.json` 和 `apps/web/screenshot.mjs` 含当前 WSL 的绝对路径；
- `scripts/dev.sh` 对 `/mnt/c/` 的检查是有意的，Mac 上条件不成立，不会因此报错；
- Playwright 配置使用 Unix 风格的 `.venv/bin/uvicorn`，适用于 WSL 和 macOS，不适用于 Windows 原生 Python 环境。

因此，这个项目必须先在 WSL 中整理和推送，不能直接让 Mac 从当前远端 `main` 开始继续开发。

特别注意以下未跟踪内容：

- `.qoder/`：本机工具配置，默认不要提交；
- `homepage.png`、`logged-in.png`：先确认是不是正式文档资产；
- `apps/web/screenshot.mjs`：含 WSL 绝对路径，提交前必须改成相对路径或排除；
- `apps/api/start.sh`：提交前检查是否包含密钥或仅适用于本机的配置；
- `apps/api/app/services/resume_scorer.py`：看起来像源码，需要连同相关测试一起审查；
- `docs/chinese-resume-quality-guide.md`：AI 或外部资料整理的内容不能当成已验证事实，提交前核对来源和表述。

## 3. 第一阶段：三台环境连接同一个 GitHub 账号

### 3.1 统一身份

三套环境使用同一个 GitHub 账号，但每台机器独立登录。不要复制另一台机器的 Git 凭据文件或 SSH 私钥。

先确定 Git 提交显示的姓名和 GitHub 邮箱：

```bash
git config --global user.name "你的 GitHub 显示名"
git config --global user.email "你的 GitHub 提交邮箱"
git config --global init.defaultBranch main
git config --global fetch.prune true
git config --global pull.ff only
```

如果不想公开真实邮箱，可在 GitHub 邮箱设置中使用账号提供的 `noreply` 邮箱。

### 3.2 Windows 安装和登录

在 PowerShell 中安装 Git 和 GitHub CLI：

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
```

关闭并重新打开 PowerShell，然后登录：

```powershell
gh auth login
gh auth setup-git
gh auth status
```

在 `gh auth login` 中选择：

- GitHub.com；
- HTTPS；
- 使用浏览器登录；
- 授权 GitHub CLI 配置 Git。

如果项目位于 WSL 的 Linux 文件系统，仍应在 WSL 内单独安装并登录 `gh`；Windows 和 WSL 是两套环境。

### 3.3 WSL 登录

在 WSL 中执行：

```bash
gh auth login
gh auth setup-git
gh auth status
```

随后在本项目中只读检查：

```bash
cd /home/codex/projects/ai-job-coach
git remote -v
git status --short --branch
```

### 3.4 Mac 安装和登录

先安装 Xcode Command Line Tools：

```bash
xcode-select --install
```

如果已经安装 Homebrew：

```bash
brew install git gh
```

然后登录：

```bash
gh auth login
gh auth setup-git
gh auth status
```

建议把 Mac 项目统一放到：

```text
~/Developer/
```

不要把正在开发的仓库放在 iCloud Drive、OneDrive 或其他会自动同步文件的目录中，以免同步程序修改 `.git`、权限或临时文件。

## 4. 第二阶段：先迁移这个 WSL 简历项目

### 4.1 暂停 Mac 端开发

在 WSL 整理并推送完成以前，Mac 端最多只做环境安装，不要基于旧的 `origin/main` 修改代码。

### 4.2 在 WSL 创建迁移分支

当前 `main` 有本地提交和未提交修改，先建立分支保全现场：

```bash
cd /home/codex/projects/ai-job-coach
git status --short --branch
git switch -c migration/wsl-20260725
```

这个操作不会自动提交未提交文件，工作区修改会继续保留在新分支中。

### 4.3 逐项审查，不使用 `git add .`

先让 WSL Codex完成以下工作：

1. 阅读 `AGENTS.md`、`PROJECT_SPEC.md` 和 `docs/product-spec.md`；
2. 查看当前 Git 差异和全部未跟踪文件；
3. 将本机工具配置、截图、缓存、密钥和绝对路径文件分类；
4. 对准备提交的代码运行相关测试；
5. 只暂存明确属于项目的文件；
6. 显示暂存区摘要，确认没有密钥、真实简历和本地数据库；
7. 提交并推送迁移分支。

暂存后必须检查：

```bash
git status --short
git diff --cached --stat
git diff --cached --check
git diff --cached
```

最后一条命令会显示准备提交的实际内容。检查时不要把可能的密钥或完整简历内容复制到聊天、日志或截图中；发现可疑文件时只报告路径和问题类型。

测试按仓库现有说明执行：

```bash
./scripts/test.sh
```

测试通过后，由 Codex 给出拟提交文件清单和提交说明。确认提交内容安全后：

```bash
git push -u origin migration/wsl-20260725
```

推荐在 GitHub 上通过 Pull Request 检查并合并到 `main`。在 GitHub 的 `main` 显示最新提交前，不进入 Mac 接管步骤。

### 4.4 给 WSL Codex 的可复制指令

```text
请负责把当前 AI 简历教练项目安全迁移到 GitHub。

工作目录是 /home/codex/projects/ai-job-coach。先完整阅读 AGENTS.md、
PROJECT_SPEC.md、docs/product-spec.md 和
docs/windows-wsl-to-mac-migration.md。

当前 main 比 origin/main 多 1 个提交，而且工作区有未提交和未跟踪文件。
请先只读盘点，再切换到 migration/wsl-20260725 分支保全现场。
逐项判断哪些是源码、测试、文档、正式资产、本机配置、截图、密钥、
数据库、真实简历或生成产物。不要使用 git add .，不要删除用户文件，
不要输出疑似密钥或完整简历内容。

重点检查 .qoder/、homepage.png、logged-in.png、
apps/web/screenshot.mjs、apps/api/start.sh、
apps/api/app/services/resume_scorer.py 和
docs/chinese-resume-quality-guide.md。绝对路径要改成基于仓库根目录的
相对路径，或者将纯本机文件加入 .gitignore。

按照 AGENTS.md，在每次改动后运行相关测试；最终运行 ./scripts/test.sh。
测试通过后，列出拟提交文件、排除文件、测试结果和风险。
只有确认暂存内容不含密钥、真实简历、数据库或本机配置后，才提交并推送
migration/wsl-20260725。不要强推，不要改写已有历史，不要删除原目录。
```

## 5. 第三阶段：盘点 Windows 的重要项目

### 5.1 先盘点，不立刻上传

在 Windows 中选定一个明确的项目父目录，例如：

```text
C:\Users\你的用户名\source
```

不要让 Codex 从 `C:\` 根目录开始扫描。先生成项目清单，建议至少记录：

| 字段 | 说明 |
|---|---|
| 项目名称 | 仓库候选名称 |
| 路径 | Windows 当前绝对路径，仅用于本地盘点 |
| 技术栈 | Python、Node、Java、.NET 等 |
| 是否已有 Git | 有则保留历史，不重新 `git init` |
| 最近修改时间 | 帮助判断优先级 |
| 启动和测试命令 | Mac 验收需要 |
| 本地数据 | 数据库、上传文件、训练数据等 |
| 敏感配置 | 只记录“存在/不存在”和文件路径，不记录值 |
| 大文件 | 判断是否需要 Git LFS 或独立备份 |
| 迁移级别 | A 必须迁移、B 归档、C 暂不迁移 |

优先级建议：

- A：还在维护、用于求职展示、未来要继续开发；
- B：有参考价值但短期不开发，只做只读归档；
- C：依赖已丢失、重复副本、纯生成产物，暂不上传。

### 5.2 给 Windows Codex 的“只读盘点”指令

把下面的 `<项目父目录>` 换成真实路径：

```text
请只读盘点 <项目父目录> 下的开发项目，为迁移到 Mac 和私有 GitHub
做准备。不要扫描整个 C 盘，不要修改、删除、移动或上传任何文件。

识别每个项目的技术栈、是否已有 .git、最近修改情况、启动方式、测试方式、
依赖锁文件、本地数据库、.env 或其他敏感配置、大于 50 MB 的文件、硬编码
Windows 绝对路径，以及 node_modules、venv、dist、build 等生成目录。

不要读取或输出密钥值、token、密码、完整简历或私人数据内容；只报告文件
路径和风险类型。生成一份 PROJECT_MIGRATION_INVENTORY.md，按 A（必须迁移）、
B（只读归档）、C（暂不迁移）提出建议。现在不要执行 git init、git add、
git commit、创建 GitHub 仓库或上传。
```

### 5.3 每次只处理一个 Windows 项目

盘点确认后，对每个 A 级项目分别执行：

1. 阅读项目已有说明和 `AGENTS.md`；
2. 如果已有 `.git`，保留历史并检查远端，不重新初始化；
3. 如果没有 `.git`，先建立 `.gitignore`、`.gitattributes`、README 和环境示例；
4. 将绝对路径改为相对路径、环境变量或平台无关的路径 API；
5. 清除代码中的密钥，但不要直接删除仍需迁移的本地密钥文件；
6. 建立依赖锁定方式；
7. 在 Windows 原环境运行测试；
8. 创建初始提交；
9. 创建私有 GitHub 仓库并推送；
10. 在 GitHub 网页确认仓库可见、默认分支正确、提交完整。

跨平台项目可考虑在仓库中加入：

```gitattributes
* text=auto eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
```

不要盲目覆盖已有 `.gitattributes`。如果项目已有换行符规则，以项目现状和测试结果为准。

常见的 `.gitignore` 候选项：

```gitignore
.env
.env.local
.venv/
venv/
node_modules/
dist/
build/
coverage/
__pycache__/
.pytest_cache/
.DS_Store
Thumbs.db
*.db
*.sqlite*
```

这只是候选清单。提交前要确认数据库是否属于必须版本化的固定测试夹具；不能因为扩展名相同就误排除正式源码资产。

### 5.4 给 Windows Codex 的“迁移单个项目”指令

```text
请安全迁移这个项目到一个新的私有 GitHub 仓库。先阅读项目内所有
AGENTS.md 和 README，并先给出只读检查结果。

如果已经存在 .git，必须保留历史；如果没有，才可以 git init。
检查并妥善处理 .env、密钥、个人数据、数据库、大文件、虚拟环境、
node_modules、构建产物、IDE/Codex 本机配置和 Windows 绝对路径。
不要输出敏感值，不要使用 git add .，不要删除原项目。

补齐清晰的中文 README、.gitignore、必要时的 .gitattributes 和不含真实
凭据的 .env.example。路径使用项目根目录相对路径、pathlib/标准路径 API
或环境变量，不要硬编码 C:\Users\...。

运行项目相关测试。测试不通过时先报告原因，不要把失败状态描述成已验证。
只暂存明确需要的文件，审查 git diff --cached 后再提交。用 gh 创建私有
仓库并推送，禁止公开仓库、强推和改写历史。最后报告仓库地址、提交 ID、
测试结果、未迁移的本地数据，以及 Mac 恢复所需但不能进入 Git 的配置项。
```

如需用 GitHub CLI 创建私有仓库，Codex 可在项目目录中使用类似命令：

```bash
gh repo create OWNER/REPOSITORY --private --source=. --remote=origin --push
```

其中 `OWNER/REPOSITORY` 必须由当前项目实际名称确定，不能把多个无关项目误推到同一个仓库。

## 6. 第四阶段：Mac 克隆和验收

### 6.1 克隆简历项目

确认迁移分支已经合并到远端 `main` 后：

```bash
mkdir -p ~/Developer
cd ~/Developer
gh repo clone R0b1nexploring/ai-job-coach
cd ai-job-coach
git status --short --branch
git log -3 --oneline
```

先不要复制 WSL 的 `.venv`、`node_modules`、`var/app.db` 或 `.env`。依赖必须在 Mac 上重新安装。

### 6.2 在 Mac 恢复环境

对这个项目：

```bash
cd ~/Developer/ai-job-coach
cp .env.example .env
./scripts/dev.sh
```

再运行：

```bash
./scripts/test.sh
```

如果 Mac 是 Apple Silicon，Python 包、Node 原生模块或本地 OCR 依赖可能需要重新构建。不要从 Windows/WSL 复制编译后的依赖目录。

只有满足下面条件，Mac 才算接管成功：

- `git status` 干净；
- 后端测试通过；
- 前端测试通过；
- 生产构建通过；
- Playwright 主流程通过；
- 本地 Mock Provider 可以在没有第三方密钥时运行；
- 页面上传、生成和下载流程正常；
- Git 没有因为换行符产生全仓库修改；
- 项目中没有 WSL 或 Windows 用户目录的硬编码路径；
- 真实简历、本地数据库和密钥没有出现在 GitHub。

### 6.3 给 Mac Codex 的可复制指令

```text
请负责在 Mac 上验收并接管 AI 简历教练项目。

先确认 GitHub 的 main 已包含 WSL 迁移后的最新提交，再克隆到
~/Developer/ai-job-coach。完整阅读 AGENTS.md、PROJECT_SPEC.md、
docs/product-spec.md 和 docs/windows-wsl-to-mac-migration.md。

不要复制 Windows/WSL 的 .venv、node_modules、数据库、缓存或编译产物。
从锁文件重新安装依赖，从 .env.example 创建本地 .env；任何真实密钥只由
用户通过安全方式在本地填写，不得读取后回显，也不得提交。

检查 Apple Silicon、Unix 路径、文件名大小写、脚本执行权限、换行符和端口
兼容性。每次修改后运行相关测试，最终运行 ./scripts/test.sh 和前端生产
构建。AI/OCR/规则输出不能当成已验证事实。

验收完成后报告：当前分支和提交 ID、通过的测试、仍失败的项目、所做的
macOS 兼容修改、未恢复的私有数据。不要删除 WSL 或 Windows 原目录。
```

### 6.4 验收其他 Windows 项目

每个仓库都在 Mac 上重复：

```bash
cd ~/Developer
gh repo clone OWNER/REPOSITORY
cd REPOSITORY
git status --short --branch
```

然后让 Mac Codex按仓库 README 重建依赖、运行测试和修复跨平台问题。每个项目单独验收，不要一次同时安装所有项目的依赖。

## 7. 路径和跨平台规则

代码中不要保存下面这类路径：

```text
C:\Users\name\project
/mnt/c/Users/name/project
/home/name/project
/Users/name/project
```

应该使用：

- 相对于仓库根目录的路径；
- Python 的 `pathlib.Path`；
- Node.js 的 `path.resolve`、`import.meta.url` 等标准能力；
- `.env` 中的可配置数据目录；
- 操作系统提供的临时目录；
- URL 与文件系统路径分开处理。

还要检查：

- Windows 文件名不区分大小写，而默认 macOS 通常也不区分；Git 和 Linux 可区分；
- `Foo.ts` 与 `foo.ts` 不应同时存在；
- Shell 脚本在 Mac/WSL 中使用 LF，并保留可执行权限；
- Windows 专用 `.bat`、`.cmd`、`.ps1` 可保留 CRLF；
- 不依赖反斜杠拼接路径；
- 不把端口、用户名和项目根目录写死；
- 不迁移 `.venv`、`node_modules` 和任何平台相关二进制文件。

## 8. Git 之外必须单独迁移的内容

GitHub 不是完整电脑备份。以下内容如果仍需要，应走独立安全通道：

| 内容 | 推荐方式 |
|---|---|
| API Key、密码、Token | 密码管理器或在 Mac 重新签发 |
| `.env` | 手工重建；只参考 `.env.example` 的变量名 |
| 真实简历和上传文件 | 加密移动硬盘或加密存储 |
| 本地 SQLite/PostgreSQL 数据 | 导出、加密传输、Mac 单独导入 |
| 大型模型和数据集 | 官方来源重新下载或受控对象存储 |
| 编辑器个人设置 | 只迁移确认无密钥的通用配置 |

这个简历项目的 `var/` 可能包含完整简历和数据库，绝对不能为了迁移方便而取消 Git 忽略。若确实需要保留，先离线加密备份，再在 Mac 本地恢复。

## 9. 日常多设备协作规则

迁移后建议采用：

```text
main：始终保持可运行
feature/<任务名>：一项任务一个分支
fix/<问题名>：一个修复一个分支
```

开始工作前：

```bash
git switch main
git pull --ff-only
git switch -c feature/short-name
```

完成并测试后再提交、推送和合并。不要在 Windows 和 Mac 上同时修改同一分支的未提交代码。

切换设备前执行：

```bash
git status --short --branch
git log -1 --oneline
```

必须确认：

- 所有需要保留的代码已提交并推送；
- GitHub 上能看到对应提交；
- 当前没有只存在于旧设备的未提交代码；
- 本地私有数据已按独立备份方案处理。

## 10. 最终完成标准

只有全部满足时，迁移才算完成：

- Windows 项目盘点表已完成；
- 所有 A 级项目都有独立私有 GitHub 仓库；
- 既有 Git 历史得到保留；
- 简历项目的 WSL 最新提交和工作区成果已安全推送；
- 每个仓库在 Mac 上均可重新安装依赖；
- 相关测试在 Mac 上实际运行并记录结果；
- 路径、换行符、大小写和脚本权限问题已处理；
- GitHub 中没有密钥、完整真实简历、本地数据库或个人数据；
- Git 之外的数据已有加密备份或明确决定不迁移；
- Mac 连续开发并成功推送一次后，才考虑归档旧设备目录。

不要因为 GitHub 页面上出现了文件就立即删除旧电脑数据。建议至少保留一份只读旧环境备份，直到 Mac 上完成一次完整开发、测试、提交、推送和重新克隆验收。
