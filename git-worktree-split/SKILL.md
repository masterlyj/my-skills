---
name: git-worktree-split
description: 当用户要求把工作区里部分未提交的改动提交到单独的新分支、且不能影响当前分支上正在进行的工作时使用本 skill，即使没有点名 worktree。典型说法："把这几个文件的改动单独放个分支提交""和现在进行中的工程分开""别动我当前分支的工作区""用 worktree 那种方式拆分"。用 git worktree 零接触完成，不动当前分支的 HEAD、未提交改动与 stash，新分支可基于其他基点。提交消息规范转 git-commit；无 WIP 保护需求的常规建分支提交不适用本 skill。
compatibility: Windows PowerShell（pwsh）环境；命令块为 PowerShell 语法（$env:TEMP、Join-Path）。类 Unix shell 需转换临时目录与路径写法。
---

# Git Worktree 零接触拆分

把工作区里部分未提交改动提交到基于其他基点的新分支，全程不动当前分支的 HEAD、未提交改动与 stash——不 switch、不 stash、不 push。分支只是 ref，提交只影响新分支。当前工作区没有需要保护的未提交改动时，直接 `git switch -c` 即可，不必用本规范。

不走 stash → 切分支 → 切回：那会暂时搬走用户 WIP，中间出岔子就滞留在 stash 里；基点与 HEAD 在带改动的文件上有交集时，switch 还会被 checkout 拦截。worktree 物理隔离操作目录，两类风险都不存在。

## 操作流程

变量：`<paths>` 待拆分路径、`<base>` 目标基点、`<branch>` 新分支名、`$wt` 临时 worktree 目录（放 `$env:TEMP`）。

### 1. 基点兼容性验证（必须最先做）

```powershell
git diff --stat <base> HEAD -- <paths>
```

为空 → 这些路径在基点与 HEAD 之间无差异，工作区改动原样适用。非空 → 停下问用户怎么处理（见边界第 1 条）。

### 2. 创建隔离 worktree

```powershell
$wt = Join-Path $env:TEMP '<branch>-wt'
git worktree add -b <branch> $wt <base>
```

主工作区不发生任何 checkout。

### 3. 在 worktree 落地改动

修改的文件从主工作区字节级复制，删除的文件在 worktree 里同样删除；`git -C $wt diff --stat` 核对只含预期路径与行数。

### 4. 分逻辑提交

消息遵循 `git-commit` 规范按粒度拆分，PowerShell 多行消息用其 §9.2 的无 BOM 临时文件法；提交后按其 §9.6 校验摘要首字节。

```powershell
git -C $wt add <paths>
git -C $wt commit -F <临时文件>
```

### 5. 清理 worktree

```powershell
git worktree remove $wt
git worktree list   # 只剩主工作目录
```

### 6. 主工作区收尾

这些路径的旧改动不撤，之后一次 `git add -A` 就会重复提交、与 `<branch>` 冲突：

```powershell
git diff <branch> -- <paths>   # 必须为空 = 与分支提交逐字节一致
git restore <paths>
git status --short             # 只剩其余进行中改动
```

用户要求保留主工作区改动时跳过本步；事后拿回：`git checkout <branch> -- <paths>`。

## 边界

- 基点差异非空不要硬复制，会把基点差异卷进提交。改走补丁：主工作区 `git diff --output=<补丁文件> -- <paths>` 生成，worktree 里 `git apply <补丁文件>`。
- 这些路径存在已暂存改动时，流程以工作区内容为基准，动手前先向用户确认以哪份为准。
- 同一分支不能被两个 worktree 同时检出；worktree 删除后即可在主目录正常 checkout。
- worktree 目录被外部强删（而非 `git worktree remove`）才需要 `git worktree prune`。
- §4 依赖 `git-commit` skill；环境中没有它时，多行提交消息切勿用 PowerShell 管道（会把 BOM 注入原生程序标准输入），用无 BOM 临时文件 `git commit -F`，提交后自查摘要首字节是类型首字母。
