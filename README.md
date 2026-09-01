# 自建 Skill 仓库

个人 AI 编程工作流的自建 skill，同时供 **Claude Code** 和 **Codex** 使用。

本仓库是这些 skill 的**唯一源**：两个客户端的 skills 目录里放的是指向本仓库的
junction，改一处三端同时生效，不会再出现副本各自漂移的问题。仓库之外（如
`~/.claude/skills`）不放副本，只放 junction。

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
```

> ⚠️ 脚本用 `$PSScriptRoot` 作为仓库根，所以 `cd` 到仓库目录后运行，或直接
> 用当前仓库路径运行。若你想让仓库留在其他盘（如 `D:\my-skills`），克隆到那里
> 再在同一目录跑 `bootstrap.ps1` 即可——junction 跨盘照常生效。

`bootstrap.ps1` 会自动为 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills`
建立 junction；后者是多数其他 code agent（Cursor、Gemini CLI 等）读取 skill 的
通用目录。某个目录不存在时会自动跳过。脚本幂等，随时可重跑。

配置在非默认位置时传参：

```powershell
.\bootstrap.ps1 -CodexDir "E:\cfg\.codex\skills"
```

## 日常维护

直接编辑本仓库里的文件，两个客户端立即生效，不需要重跑 bootstrap——只有**新增或
删除 skill** 时才需要重跑（新增要建链接，删除要清理失效链接）。

```powershell
# 验证链接是否正确指向本仓库
Get-Item $env:USERPROFILE\.claude\skills\python-quality | Select-Object LinkType, Target
```

## 外部来源 skill（原样引入，以原仓库为准）

`frontend-slides`、`repo-docs`、`repo-docs-zh` 不是自建的，是原样拷贝自其他人的
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
- **插件 skill**（如 `mattpocock-skills`）：由 `/plugin` 从官方 marketplace 安装，
  只读托管、自动更新。
- 本地独有、未纳管的 skill 放在 `~/.claude/skills` 下但不进本仓库（保持原样）。
