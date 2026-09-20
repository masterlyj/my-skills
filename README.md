# 自建 Skill 仓库

个人 AI 编程工作流的 skill 集合，供 **Claude Code**、**OpenCode**、**Codex** 等
客户端使用。

本仓库是**自建 skill 的唯一源**：各客户端的 skills 目录里放的是指向本仓库的
junction，改一处多端同时生效，不会再出现副本各自漂移的问题。仓库之外
（如 `~/.claude/skills`）不放副本，只放 junction。

第三方 skill 单独放在 `~/.skills-vendor/`，由脚本同步上游——见
[外部来源 skill](#外部来源-skill)。

## 目录

### 纪律类（常驻守则）

配合 `~/.claude/CLAUDE.md` 一起使用的行为规范，写代码时始终对照。

| Skill | 用途 |
|---|---|
| `karpathy-guidelines` | 减少 AI 编程常见错误的行为准则（防过度设计、外科手术式修改、假设显式化、目标驱动） |
| `python-quality` | Python 可读性规范（module/函数/类 docstring、Pydantic 专项、行内注释） |
| `git-commit` | Git 提交消息规范（约定式提交 + 中文祈使句 + 跨 shell 提交写法） |

### 工作流类（按需调用）

处理具体任务时才触发的 skill。

| Skill | 用途 |
|---|---|
| `exec-report-writing` | 技术材料转领导可读的汇报 |
| `git-worktree-split` | 零接触拆分工作区部分改动到独立分支（worktree 隔离操作规程） |
| `qa-knowledge-organizer` | 把代码项目材料整理成面试/答辩用 QA（`qa/README.md` 作金字塔顶层，五部分 Q&A：讲清楚 + 核心答案 + 关键词锚点 + 补充与边界，配独立证据索引与复核记录） |
| `langchain-guide` | LangChain ChatModel 调用实践（结构化输出、工具调用与参数校验、三层重试/超时、多模型 fallback、同步/异步调用） |
| `frontend-slides`² | 零依赖 HTML 演示文稿生成 |
| `repo-docs`² | 仓库理解文档生成 |
| `repo-docs-zh`² | `repo-docs` 的中文覆盖层 |

² 标记的三个是原样引入的外部 skill，见下方「外部来源 skill」。

## 仓库位置

Junction 是目录重定向，**可跨盘**（`D:`、`E:` 等都行），因此本仓库可以放在任意
本地路径，不必和 `~/.claude/skills`（通常 `C:`）同盘。**默认推荐放
`$env:USERPROFILE\.skills`**（即 `C:\Users\<你>\.skills`），以便各客户端统一引用。

> 移动仓库后要**重跑一次 `bootstrap.ps1`**，把已有的 junction 重新指向新位置，
> 否则会变成悬空链接（bootstrap 幂等，会先摘除旧链接再重建）。

## 首次部署 / 换设备

```powershell
# 1. 克隆到默认位置（注意目录：$env:USERPROFILE\.skills）
git clone https://github.com/masterlyj/my-skills.git $env:USERPROFILE\.skills
cd $env:USERPROFILE\.skills   # 一定要在这个目录里跑脚本

# 2. 建立 junction（对 ~/.claude/skills、~/.codex/skills、~/.agents/skills）
.\bootstrap.ps1

# 3. 拉取第三方 skill 到 vendor，并重建链接
#    注意：vendor 目录不在 git 里，换设备后必须重新同步一次
.\sync-vendor.ps1
```

> ⚠️ **第 3 步不能省。** `~/.skills-vendor/` 是仓库外的独立目录，`git clone`
> 不会带过来。跳过它的话 vendor 里的 skill 全部缺失，而 `bootstrap.ps1` 只会
> 静默跳过（它把「vendor 目录不存在」当作正常情况），你不会收到任何报错。

> ⚠️ 脚本用 `$PSScriptRoot` 作为仓库根，所以 `cd` 到仓库目录后运行，或直接
> 用当前仓库路径运行。若你想让仓库留在其他盘（如 `D:\my-skills`），克隆到那里
> 再在同一目录跑 `bootstrap.ps1` 即可——junction 跨盘照常生效。

`bootstrap.ps1` 会自动为 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills`
建立 junction；后者是多数其他 code agent（Cursor、Gemini CLI、OpenCode 等）读取
skill 的通用目录。某个目录不存在时会自动跳过。脚本幂等，随时可重跑。

配置在非默认位置时传参：

```powershell
.\bootstrap.ps1 -CodexDir "E:\cfg\.codex\skills"
.\bootstrap.ps1 -VendorDir "D:\vendor-skills"
```

## 日常维护

直接编辑本仓库里的文件，各客户端立即生效，不需要重跑 bootstrap——只有**新增或
删除 skill** 时才需要重跑（新增要建链接，删除要清理失效链接）。

```powershell
# 验证链接是否正确指向源目录
Get-Item $env:USERPROFILE\.claude\skills\python-quality | Select-Object LinkType, Target

# 确认两处消费目录下没有副本（输出应为空）
Get-ChildItem $env:USERPROFILE\.claude\skills\ -Force |
    Where-Object { -not $_.LinkType -and $_.PSIsContainer } | Select-Object Name
Get-ChildItem $env:USERPROFILE\.agents\skills\ -Force |
    Where-Object { -not $_.LinkType -and $_.PSIsContainer } | Select-Object Name
```

> `~/.agents/skills/` 下住着 `lark-*` 等**真实目录**（由 `lark-cli` 管理），
> 所以第二条命令的输出**非空是正常的**——只需确认其中没有本仓库或 vendor 的
> skill 名即可。`bootstrap.ps1` 遇到非链接目录会跳过并警告，不会删除它们。

## 外部来源 skill

外部来源的 skill 有**两种**管理方式，区别在于「要不要跟上游更新」：

| 方式 | 存放位置 | 更新方式 | 适用 |
|---|---|---|---|
| **vendor（脚本同步）** | `~/.skills-vendor/`（**仓库外**） | `sync-vendor.ps1` 自动拉取 | 上游活跃维护、希望持续跟随 |
| **内联（手动覆盖）** | 本仓库内 | 手动覆盖 | 上游基本不动 |

两者都通过 junction 暴露给各客户端，用法上无差别。

### 方式一：vendor 目录（推荐用于活跃上游）

第三方 skill 存放在 **`~/.skills-vendor/`** —— 一个**独立于本仓库的目录**，由
`sync-vendor.ps1` 从上游同步。放在仓库外的原因：这些文件不由你维护，纳入本仓库
的 git 历史只会让上游更新和本地提交互相纠缠。

当前 vendor 内的 skill：

| Skill | 来源 | 上游桶路径 |
|---|---|---|
| `writing-for-agents` | [mattpocock/skills](https://github.com/mattpocock/skills) | `skills/productivity/` |
| `grilling` | 同上 | `skills/productivity/` |
| `wait-what` | 同上 | `skills/productivity/` |
| `diagnosing-bugs` | 同上 | `skills/engineering/` |
| `tdd` | 同上 | `skills/engineering/` |
| `codebase-design` | 同上 | `skills/engineering/` |
| `domain-modeling` | 同上 | `skills/engineering/` |
| `research` | 同上 | `skills/engineering/` |
| `resolving-merge-conflicts` | 同上 | `skills/engineering/` |
| `aihot` | [KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills) | `aihot/` |

清单记录在 `~/.skills-vendor/.vendor.json`，**多上游**结构如下：

```json
{
  "sources": {
    "owner/repo": {
      "repo": "https://github.com/owner/repo.git",
      "branch": "main",
      "upstreamCommit": "<上次同步的 commit>",
      "syncedAt": "<上次同步时间>",
      "skills": { "<本地名>": "<上游桶路径>" }
    }
  }
}
```

要增删 skill，改对应 source 的 `skills` 字段；要增减上游，改 `sources` 顶层键
（key 用 `owner/repo`）。

**同步上游：**

```powershell
cd $env:USERPROFILE\.skills
.\sync-vendor.ps1                          # 同步全部上游 + 重建链接
.\sync-vendor.ps1 -Only "owner/repo"       # 只同步指定上游
.\sync-vendor.ps1 -Force                   # 无条件覆盖
.\sync-vendor.ps1 -SkipBootstrap           # 只同步文件，不重建链接
```

每个上游的 commit 未变时会单独跳过，不会无谓覆盖；其余上游照常处理。

> ⚠️ **vendor 是上游镜像，不要直接改。** 同步时是「整目录删除再拷贝」，在 vendor
> 里的任何修改都会丢失。这些 skill 一律以原仓库为准。

> **运行时文件保护**：skill 目录下以 `.` 开头的隐藏文件视为**本机运行时状态**
> （如 AIHOT 的 `.aihot-actor-id`），同步前备份、同步后还原，不会被覆盖或删除。
> 上游包本身不应包含任何 dotfile。

### `aihot` 的特殊说明

aihot 的官方安装器（`install.sh`）会在发现目标目录是 symlink 时**主动报错退出**：

```
[[ ! -L "$INSTALL_DIR" ]] || fail "target is a symlink; ..."
```

本仓库把 aihot 装成 junction，因此**不能再跑官方 `install.sh` 更新**——请一律走
`.\sync-vendor.ps1 -Only "KKKKhazix/khazix-skills"`。这也正是把它纳入 vendor
统一管理的目的。

- 上游仓库是**分发源目录**（含 `install.sh`、`README.md`、`manifest.sha256` 等），
  vendor 按「整目录镜像」同步，多出的这几个文件无害，不参与 skill 运行。
- `.aihot-actor-id` 是本机随机生成的匿名 UUID（仅用于跨渠道去重，非账号/密钥），
  属运行时状态，同步时受上述保护机制保留。

### 方式二：内联在本仓库（上游不活跃时）

`frontend-slides`、`repo-docs`、`repo-docs-zh` 直接放在本仓库内，原样拷贝自其他人的
开源仓库，本地不做任何修改：

| Skill | 来源仓库 | 路径 |
|---|---|---|
| `frontend-slides` | https://github.com/zarazhangrui/frontend-slides | 仓库根目录（不含 `plugins/`，那是给 `/plugin` marketplace 用的打包镜像，内容跟 skill 本体重复） |
| `repo-docs` | https://github.com/YurunChen/repo-docs-skills | `skills/repo-docs` |
| `repo-docs-zh` | https://github.com/YurunChen/repo-docs-skills | `skills/repo-docs-zh` |

**更新方式：** 直接用原仓库对应路径的内容整体覆盖本地目录即可，不需要 diff、不
需要保留本地改动、不需要合并——因为本地从来没改过。AI 拉取更新时应以原仓库内容
为唯一权威来源，发现不一致就以原仓库为准覆盖，而不是反向"修正"原仓库的写法。

这三个 skill 基本不会主动更新，只有明确要求"检查/同步这三个 skill"时才去拉取。


## 不在本仓库的 skill

- **`lark-*`（28 个）**：由 `lark-cli` 通过 `~/.agents/.skill-lock.json` 管理，
  从 `open.feishu.cn` 自动更新，不纳入版本控制以免和上游更新冲突。
- **第三方 skill**：见上方「外部来源 skill」，放在 `~/.skills-vendor/` 或本仓库内。
- 本地独有、未纳管的 skill 放在 `~/.claude/skills` 下但不进本仓库（保持原样）。

> **关于 `/plugin` 方式**：mattpocock 那套 skill 也提供 Claude Code plugin 安装
> （`/plugin install mattpocock-skills`），但那**只对 Claude Code 生效**——
> OpenCode、Codex 等只读 skills 目录，读不到 plugin。本仓库统一用 junction，
> 所以走 vendor 路线，不走 plugin。**不要两种方式同时装**，否则每个 skill 会出现
> 两遍。
