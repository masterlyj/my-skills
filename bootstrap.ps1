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

.EXAMPLE
    .\bootstrap.ps1
    在默认位置建立链接。

.EXAMPLE
    .\bootstrap.ps1 -CodexDir "E:\cfg\.codex\skills"
    Codex 配置在非默认位置时指定路径。
#>
param(
    [string]$ClaudeDir = (Join-Path $env:USERPROFILE ".claude\skills"),
    [string]$CodexDir = (Join-Path $env:USERPROFILE ".codex\skills")
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot

# 移除已有条目。junction 必须用 Directory.Delete 只摘链接，
# 否则 Remove-Item -Recurse 会顺着链接删掉仓库里的真实文件。
function Remove-Existing {
    param([string]$Path)
    $item = Get-Item $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        [System.IO.Directory]::Delete($Path, $false)
    }
    else {
        Remove-Item $Path -Recurse -Force -Confirm:$false
    }
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

foreach ($target in @($ClaudeDir, $CodexDir)) {
    if (-not (Test-Path $target)) {
        Write-Host "跳过 $target（目录不存在，该客户端未安装）" -ForegroundColor Yellow
        continue
    }

    Write-Host "-> $target" -ForegroundColor Cyan
    foreach ($name in $skills) {
        $link = Join-Path $target $name
        if (Test-Path $link) { Remove-Existing $link }
        New-Item -ItemType Junction -Path $link -Target (Join-Path $repo $name) | Out-Null
        Write-Host "   + $name"
    }
}

Write-Host ""
Write-Host "完成。用 Get-Item <path> | Select-Object LinkType,Target 可验证链接。" -ForegroundColor Green