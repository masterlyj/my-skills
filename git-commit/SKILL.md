---
name: git-commit
description: Git 提交消息质量规范。用于编写、审查、拆分或校验提交消息、合并请求标题、压缩合并标题和发布变更记录；基于约定式提交，适配中文祈使句、影响范围选择、破坏性变更、提交粒度和钩子/流水线自动化校验。禁止添加人工智能署名、工具署名或未经要求的协作者署名。
---

# Git 提交规范

本规范让 Git 历史同时满足三件事：人能读懂、机器能校验、发布流程能复用。默认使用中文描述。

## 1. 提交消息格式

```text
<type>[(scope)][!]: <subject>

[body]

[footer]
```

- `type`：提交类型，必填。
- `scope`：影响范围，可选。
- `!`：破坏性变更标记，可选。可单独使用，也可与 `BREAKING CHANGE:` 页脚同时使用。
- `subject`：一句话说明本次提交带来的结果，必填。
- `body`：解释为什么改、为什么这样改，可选。
- `footer`：关联事项、破坏性变更等元信息，可选。

禁止自动添加人工智能署名、工具署名或未经要求的协作者署名，例如 `Generated-by:`、`Co-authored-by:`、`Signed-off-by:`。只有用户明确要求时，才可以加入署名类页脚。

## 2. 类型规则

| 类型 | 用途 |
|------|------|
| `feat` | 新功能，对应语义版本的小版本 |
| `fix` | 缺陷修复，对应语义版本的补丁版本 |
| `refactor` | 重构，不改变外部行为，也不修复缺陷 |
| `perf` | 性能优化 |
| `docs` | 文档变更 |
| `test` | 测试变更 |
| `style` | 格式变更，例如空格、缩进、换行，不影响逻辑 |
| `build` | 构建系统、打包配置、依赖管理 |
| `ci` | 持续集成或持续交付配置 |
| `chore` | 维护性杂项 |
| `revert` | 回滚提交 |

选择原则：能用上表解决时不新增类型；依赖升级优先用 `build(deps)`；发布提交优先交给发布工具生成；安全修复可用 `fix(security)`，除非团队另有约定。

## 3. 影响范围规则

`scope` 回答“这次改动主要影响哪里”。优先使用模块名、业务域、包名、服务名或目录名，例如 `api`、`retrieval`、`auth`、`web`、`docs`。

规则：

- 小项目或影响范围很清楚时可以省略。
- 不要写过细的影响范围，例如 `button-color`、`line-42`。
- 一个提交影响多个范围时，选择用户最关心的主范围。
- 单仓多包项目优先使用包名、服务名或应用名。
- 团队项目建议维护推荐影响范围列表，避免同义词混用。

## 4. 摘要规则

摘要用中文祈使句，描述提交带来的结果。

规则：

- 不超过 72 字符，包含 `type(scope): ` 前缀。
- 不加句号。
- 使用动词开头：新增、修复、删除、迁移、限制、补充、合并、拆分。
- 不写“修改了”“更新了”“优化了一下”“处理一些问题”。
- 不复述文件名，除非文件名就是用户理解改动的关键。

推荐：

```text
fix(api): 修复 stats 接口私有属性访问
docs(readme): 补充 Docker 启动说明
refactor(search): 合并重复的过滤条件构造逻辑
```

不推荐：

```text
fix(api): 修改了 stats 的一些问题
docs: 更新了一下文档
refactor: 优化代码
```

## 5. 正文规则

正文优先解释为什么改、为什么这样改；必要时补充关键实现路径，但不要重复差异内容。

需要写正文：多文件改动、行为变化不明显、重构、迁移、兼容性改造、复杂缺陷修复、需要解释设计取舍、有破坏性影响。

可以省略正文：

```text
docs(readme): 修正安装命令拼写
test(api): 增加 stats 接口空响应用例
```

写法：摘要和正文之间空一行；每行不超过 72 字符；使用完整句子说明背景、原因和取舍；多点原因可以用列表。

## 6. 页脚规则

页脚用于放机器可识别或流程相关的元信息。

常见页脚：

```text
BREAKING CHANGE: /search 返回字段从 result 改为 data，调用方需要同步改造解析逻辑。
Refs: MW-123
Closes: #456
```

规则：

- 破坏性变更必须写 `BREAKING CHANGE:`（`BREAKING-CHANGE:` 等价）。
- `BREAKING CHANGE:` 必须说明破坏了什么、谁受影响、如何迁移。
- 页脚 token 用连字符代替空格（如 `Acked-by`、`Reviewed-by`）；`BREAKING CHANGE` 是唯一允许空格的例外。
- 不要把普通解释放到页脚；普通解释写在正文。
- 不添加人工智能署名、工具署名或未经要求的协作者署名。

破坏性变更示例：

```text
feat(api)!: 调整检索接口响应结构

BREAKING CHANGE: /search 返回字段从 result 改为 data，调用方需要同步改造解析逻辑。
```

## 7. 提交粒度

好的提交不只是消息格式正确，还要边界清楚。

规则：

- 一个提交只表达一个逻辑改动。
- 行为变更、重构、格式化尽量拆开。
- 不把临时调试、无关文件、自动生成文件混入业务提交。
- 如果必须混合提交，在正文中说明原因。
- 压缩合并时，最终合并请求标题或压缩合并提交必须符合本规范。

拆分建议：

```text
style: 格式化检索模块
refactor(retrieval): 提取过滤条件构造函数
fix(retrieval): 修复空过滤条件导致的查询失败
```

## 8. 特殊提交

以下提交可以豁免部分规则，但不应进入长期主干历史，除非团队流程允许：`Merge branch '...'`、`Revert "..."`、`fixup! ...`、`squash! ...`、`WIP: ...`。

规则：`fixup!` 和 `squash!` 应在合并前通过变基清理；`WIP` 只用于本地或临时分支；`revert` 提交保留 Git 自动生成的原始信息即可，必要时补充原因。

## 9. 实际提交方式

**严禁混用不同 shell 的语法**：在 Git Bash 中使用 PowerShell 的 here-string（`@'...'@`），`@` 会被当作普通字符混入提交信息；在 PowerShell 中使用 heredoc 同样会失败。写错时用当前 shell 的正确语法执行 `git commit --amend`（PowerShell 见 §9.2 的临时文件写法，Git Bash 见 §9.3 的 `--amend -F -`）重写即可。

提交前先按 §9.5 确认暂存区只包含本次任务相关改动，提交后按 §9.6 确认首字符。

### 9.1 简单提交

没有正文时，各 shell 都可以直接使用一行提交：

```bash
git commit -m "fix(api): 修复 stats 接口私有属性访问"
```

### 9.2 PowerShell 多行提交

**Windows PowerShell 5.1 优先用无 BOM 临时文件**，不要用管道：

```powershell
$msg = @'
feat(retrieval): 增加混合检索召回链路

为支持关键词召回和向量召回同时参与排序，检索入口需要统一返回候选集。
本次提交只引入召回链路，不调整最终排序策略。

Refs: MW-123
'@
$path = Join-Path $env:TEMP 'cmsg.txt'
[System.IO.File]::WriteAllText($path, $msg, (New-Object System.Text.UTF8Encoding($false)))
git commit -F $path
Remove-Item $path -Force
```

`UTF8Encoding($false)` 是唯一可靠的无 BOM 写法。`Set-Content -Encoding utf8` 和
`Out-File -Encoding utf8` 在 5.1 下**都带 BOM**，这个场景不能用。

**为什么不用管道**：`$字符串 | git commit -F -` 在 5.1 下把内容重定向进 git 的标准输入时，
用的是 `[Console]::OutputEncoding`，两个方向都会坏且都不报错：

| 环境 | 表现 |
|------|------|
| 原生 5.1（`$OutputEncoding` 为 ASCII） | 中文变成 `????`，消息报废 |
| 控制台设过 UTF-8（`[Console]::OutputEncoding` 带前导 `EF BB BF`） | 消息头多一个 BOM |
| PowerShell 7+（UTF-8 无 BOM） | 正常 |

BOM 混进摘要后 git 会原样存下，约定式提交的校验钩子和变更日志工具从首字符起匹配
`type(scope):`，会识别不到类型；提交当时不报错，问题到流水线才暴露。注意只设
`$OutputEncoding` 无效——它本身通常不带前导字节，真正生效的是 `[Console]::OutputEncoding`。
影响面不限于 git：这个环境下任何 `字符串 | 原生程序.exe` 都会多一个 BOM。

PowerShell 7+ 可以用管道简写 `$msg | git commit -F -`，但临时文件写法在所有版本都安全。

如果只需要 subject，用 `-m`（走命令行参数，不经标准输入，不受编码影响）：

```powershell
git commit -m "docs(readme): 补充 Docker 启动说明"
```

### 9.3 Git Bash 多行提交

Git Bash 推荐用 heredoc 通过标准输入传给 `git commit -F -`：

```bash
git commit -F - <<'EOF'
feat(retrieval): 增加混合检索召回链路

为支持关键词召回和向量召回同时参与排序，检索入口需要统一返回候选集。
本次提交只引入召回链路，不调整最终排序策略。

Refs: MW-123
EOF
```

> `<<'EOF'` 中的单引号不可省略：它关闭变量插值和命令替换，保证内容原样传给 Git；写成 `<<EOF` 会让 `$var` 和反引号被 shell 展开。

如果只需要 subject，也可以用：

```bash
git commit -m "docs(readme): 补充 Docker 启动说明"
```

### 9.4 跨平台备选：多个 -m 参数

不涉及复杂正文格式时，最简单的跨平台写法是多个 `-m` 参数，Git 会自动在参数之间插入空行，PowerShell 和 Git Bash 均适用：

```bash
git commit -m "feat(retrieval): 增加混合检索召回链路" -m "为支持关键词和向量召回同时参与排序，统一返回候选集。"
```

### 9.5 提交前检查

```bash
git status --short
git diff --cached
```

确认无误后再提交；如果发现暂存了无关文件，先调整暂存区，不要把无关改动混进提交。

### 9.6 提交后检查首字符

摘要必须以 `type` 的第一个字母开头，前面不能有 BOM 等不可见字符。中文提交消息、
或用 `-F` / 标准输入传消息时尤其要查——BOM 在终端和 `git log` 里都看不见，
只在校验钩子和变更日志工具里报错：

```bash
git log -1 --pretty=format:%s | od -c | head -1   # Git Bash
```

PowerShell 下不要用管道验证（管道自身会加 BOM，见 §9.2），用 `Format-Hex`，
它是 cmdlet、不经过原生进程的标准输入：

```powershell
git log -1 --pretty=format:'%s' | Format-Hex | Select-Object -First 2
```

首字节应当直接是类型的首字母（如 `fix` 是 `66`、`feat` 是 `66`、`docs` 是 `64`），
出现 `EF BB BF` 说明混入 BOM，按 §9.2 用无 BOM 临时文件执行 `git commit --amend -F $path` 重写。

`Format-Hex` 会把中文显示成 `3F`（`?`），那是它的显示限制、不是消息坏了；这一步只看首字节。
需要连中文一起核对时，绕开 shell 用 Git 自己的输出：

```powershell
python -c "import subprocess; raw=subprocess.run(['git','log','-1','--pretty=format:%s'],capture_output=True).stdout; print(repr(raw[:6]), raw.decode('utf-8'))"
```

## 10. 快速自检清单

提交前确认：

- [ ] 类型准确。
- [ ] 影响范围清楚，或确实可以省略。
- [ ] 摘要是中文祈使句，不超过 72 字符，不加句号。
- [ ] 一个提交只表达一个逻辑改动。
- [ ] 复杂改动有正文解释原因和关键取舍。
- [ ] 破坏性变更至少使用 `!` 或 `BREAKING CHANGE:` 之一标记，推荐同时使用。
- [ ] 没有人工智能署名、工具署名或未经要求的协作者署名。
- [ ] 提交后按 §9.6 确认摘要首字符就是类型首字母，没有混入 BOM。

规范起作用的标志：看提交历史就能理解项目演进脉络；工具能稳定生成变更日志或判断版本影响；代码审查不再花时间猜“这次提交到底为什么改”。
