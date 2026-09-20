<#
.SYNOPSIS
    把自建与第三方 skill 以 junction 方式链接到各 code agent 的 skills 目录。

.DESCRIPTION
    有两个 skill 源：

    - 本仓库（$PSScriptRoot）：自建 skill，纳入 git 管理。
    - vendor 目录（见 -VendorDir）：第三方 skill，由 sync-vendor.ps1 从上游同步，
      不纳入本仓库的 git 管理。

    执行本脚本后，Claude Code、Codex、OpenCode 等读到的都是源目录里的同一份
    文件，改一处多端同时生效。

    同名冲突时自建优先：vendor 里与自建同名的 skill 会被跳过并提示。

    脚本幂等，可重复执行：已存在的链接或目录会先被安全移除再重建。

.PARAMETER ClaudeDir
    Claude Code 的 skills 目录，默认 ~/.claude/skills。

.PARAMETER CodexDir
    Codex 的 skills 目录，默认 ~/.codex/skills。

.PARAMETER AgentsDir
    通用 agent skills 目录，默认 ~/.agents/skills。多数其他 code agent
    （Cursor、Gemini CLI、OpenCode、Kode 等）会读取这个通用目录。

.PARAMETER VendorDir
    第三方 skill 的源目录，默认 ~/.skills-vendor。目录不存在时自动跳过，
    只处理自建 skill——因此该参数对未使用 vendor 的环境是向后兼容的。

.EXAMPLE
    .\bootstrap.ps1
    在默认位置建立链接。

.EXAMPLE
    .\bootstrap.ps1 -CodexDir "E:\cfg\.codex\skills"
    Codex 配置在非默认位置时指定路径。

.EXAMPLE
    .\bootstrap.ps1 -VendorDir "D:\vendor-skills"
    从非默认位置读取第三方 skill。
#>
param(
    [string]$ClaudeDir = (Join-Path $env:USERPROFILE ".claude\skills"),
    [string]$CodexDir = (Join-Path $env:USERPROFILE ".codex\skills"),
    [string]$AgentsDir = (Join-Path $env:USERPROFILE ".agents\skills"),
    [string]$VendorDir = (Join-Path $env:USERPROFILE ".skills-vendor")
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
function Get-SkillNames {
    param([string]$Root)
    if (-not (Test-Path $Root)) { return @() }
    return @(Get-ChildItem $Root -Directory -Force |
        Where-Object { Test-Path (Join-Path $_.FullName 'SKILL.md') } |
        Select-Object -ExpandProperty Name)
}

$ownSkills = Get-SkillNames $repo
$vendorSkills = Get-SkillNames $VendorDir

# 自建优先：vendor 里与自建同名的直接剔除，并提示。
$shadowed = @($vendorSkills | Where-Object { $ownSkills -contains $_ })
$vendorSkills = @($vendorSkills | Where-Object { $ownSkills -notcontains $_ })

# 记录每个 skill 的来源，建链接时按名字取对应根目录。
$skillSource = @{}
foreach ($n in $ownSkills) { $skillSource[$n] = $repo }
foreach ($n in $vendorSkills) { $skillSource[$n] = $VendorDir }

$skills = @($ownSkills + $vendorSkills | Sort-Object -Unique)

if (-not $skills) {
    Write-Host "没有找到任何 skill（缺 SKILL.md）" -ForegroundColor Red
    Write-Host "  自建源: $repo" -ForegroundColor DarkGray
    Write-Host "  vendor: $VendorDir" -ForegroundColor DarkGray
    exit 1
}

Write-Host "自建源: $repo（$($ownSkills.Count) 个）"
if (Test-Path $VendorDir) {
    Write-Host "vendor: $VendorDir（$($vendorSkills.Count) 个）"
}
else {
    Write-Host "vendor: $VendorDir（不存在，跳过）" -ForegroundColor DarkGray
}
if ($shadowed) {
    Write-Host ""
    Write-Host "! 以下 $($shadowed.Count) 个 skill 自建与 vendor 同名，已按自建优先处理：" -ForegroundColor Yellow
    Write-Host "  $($shadowed -join ', ')" -ForegroundColor Yellow
    Write-Host "  如需改用 vendor 版本，请移除自建目录或改用其他 -VendorDir。" -ForegroundColor Yellow
}
Write-Host ""
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
        New-Item -ItemType Junction -Path $link -Target (Join-Path $skillSource[$name] $name) | Out-Null
        Write-Host "   + $name"
    }
    if ($skipped) {
        Write-Host "   跳过 $($skipped.Count) 个：$($skipped -join ', ')" -ForegroundColor Yellow
        Write-Host "   这些是其他工具管理的真实目录，如需接管请先自行备份并删除。" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "完成。用 Get-Item <path> | Select-Object LinkType,Target 可验证链接。" -ForegroundColor Green