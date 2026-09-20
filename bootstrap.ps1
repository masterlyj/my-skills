<#
.SYNOPSIS
    把本仓库的 skill 以 junction 方式链接到 Claude Code 和 Codex 的 skills 目录。

.DESCRIPTION
    本仓库是自建 skill 的唯一源。执行本脚本后，Claude Code 与 Codex 读到的都是
    本仓库里的同一份文件，改一处三端同时生效。

    脚本幂等，可重复执行：已存在的链接或目录会先被安全移除再重建。

.PARAMETER ClaudeDir
    Claude Code 的 skills 目录，默认 ~/.claude/skills。

.PARAMETER CodexDir
    Codex 的 skills 目录，默认 ~/.codex/skills。

.PARAMETER AgentsDir
    通用 agent skills 目录，默认 ~/.agents/skills。多数其他 code agent
    （Cursor、Gemini CLI、Kode 等）会读取这个通用目录。

.EXAMPLE
    .\bootstrap.ps1
    在默认位置建立链接。

.EXAMPLE
    .\bootstrap.ps1 -CodexDir "E:\cfg\.codex\skills"
    Codex 配置在非默认位置时指定路径。
#>
param(
    [string]$ClaudeDir = (Join-Path $env:USERPROFILE ".claude\skills"),
    [string]$CodexDir = (Join-Path $env:USERPROFILE ".codex\skills"),
    [string]$AgentsDir = (Join-Path $env:USERPROFILE ".agents\skills")
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot

# 移除本脚本此前建立的链接。只摘链接本身，不碰内容——junction 必须用
# Directory.Delete，Remove-Item -Recurse 会顺着链接删掉仓库里的真实文件。
function Remove-Link {
    param([string]$Path)
    [System.IO.Directory]::Delete($Path, $false)
}

# 判断目标是本脚本建的链接（可安全覆盖），还是别的工具管理的真实目录。
# 目标目录里可能住着不受本仓库管理的 skill——例如 ~/.agents/skills 下的
# lark-*，那些是 lark-cli 按 ~/.agents/.skill-lock.json 维护的真实目录。
# 一旦仓库里出现同名 skill，覆盖前必须先确认这不是别人的东西：
# 真实目录一律跳过并警告，绝不删除。
function Test-IsOurLink {
    param([string]$Path)
    $item = Get-Item $Path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return $false }
    return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

# 只把带 SKILL.md 的目录当作 skill，跳过 .git 等辅助目录。
$skills = Get-ChildItem $repo -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'SKILL.md') } |
    Select-Object -ExpandProperty Name

if (-not $skills) {
    Write-Host "仓库里没有找到任何 skill（缺 SKILL.md）" -ForegroundColor Red
    exit 1
}

Write-Host "源仓库: $repo"
Write-Host "待链接 skill（$($skills.Count) 个）: $($skills -join ', ')"
Write-Host ""

foreach ($target in @($ClaudeDir, $CodexDir, $AgentsDir)) {
    if (-not (Test-Path $target)) {
        Write-Host "跳过 $target（目录不存在，该客户端未安装）" -ForegroundColor Yellow
        continue
    }

    Write-Host "-> $target" -ForegroundColor Cyan
    $skipped = @()
    foreach ($name in $skills) {
        $link = Join-Path $target $name
        if (Test-Path $link) {
            if (Test-IsOurLink $link) {
                Remove-Link $link
            }
            else {
                # 真实目录，不是本脚本建的——多半由别的工具管理。不能删。
                Write-Host "   ! $name（已存在且非链接，跳过，未改动）" -ForegroundColor Yellow
                $skipped += $name
                continue
            }
        }
        New-Item -ItemType Junction -Path $link -Target (Join-Path $repo $name) | Out-Null
        Write-Host "   + $name"
    }
    if ($skipped) {
        Write-Host "   跳过 $($skipped.Count) 个：$($skipped -join ', ')" -ForegroundColor Yellow
        Write-Host "   这些是其他工具管理的真实目录，如需接管请先自行备份并删除。" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "完成。用 Get-Item <path> | Select-Object LinkType,Target 可验证链接。" -ForegroundColor Green