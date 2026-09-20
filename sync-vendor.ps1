<#
.SYNOPSIS
    从多个上游同步第三方 skill 到 vendor 目录，然后重建全部 junction 链接。

.DESCRIPTION
    vendor 目录（默认 ~/.skills-vendor）存放不在本仓库 git 管理内的第三方
    skill，清单记录在同目录的 .vendor.json 里。

    清单结构（多上游）：

        {
          "sources": {
            "owner/repo": {
              "repo":           "https://github.com/owner/repo.git",
              "branch":         "main",
              "upstreamCommit": "<上次同步的 commit，首次为空>",
              "syncedAt":       "<上次同步时间，首次为空>",
              "skills":         { "<本地名>": "<上游桶路径>" }
            }
          }
        }

    本脚本：

      1. 读取 .vendor.json，遍历每个上游；
      2. 把该上游浅克隆到临时目录；
      3. 按清单把每个 skill 从上游的桶路径摊平复制到 vendor 根目录；
      4. 回写该上游的 commit 与同步时间；
      5. 全部完成后调用 bootstrap.ps1 重建各 agent 目录下的 junction。

    覆盖策略：vendor 目录里的内容视为上游快照，同步时直接覆盖。若某个 skill
    的本地内容与上游不同，脚本会列出该文件并停下（除非 -Force）——因为对
    vendor 的本地修改在下次同步时会丢失，值得确认一次。

    运行时文件保护：skill 目录下以 "." 开头的隐藏文件视为本机运行时状态
    （例如 AIHOT 的 .aihot-actor-id），不属于上游包，同步前备份、同步后
    还原，不会被覆盖或删除。上游包本身不应包含任何 dotfile。

.PARAMETER VendorDir
    vendor 目录，默认 ~/.skills-vendor。

.PARAMETER Only
    只同步指定上游（按清单里的 key，如 "KKKKhazix/khazix-skills"）。
    省略时同步全部。

.PARAMETER Force
    无条件覆盖本地改动，不询问。

.PARAMETER SkipBootstrap
    只同步文件，不重建链接。用于先看差异再决定。

.EXAMPLE
    .\sync-vendor.ps1
    同步全部上游并重建链接，本地有改动时停下询问。

.EXAMPLE
    .\sync-vendor.ps1 -Only "KKKKhazix/khazix-skills"
    只同步 aihot 所在的那个上游。

.EXAMPLE
    .\sync-vendor.ps1 -Force
    无条件覆盖。

.EXAMPLE
    .\sync-vendor.ps1 -SkipBootstrap
    只同步，之后手动跑 bootstrap.ps1。
#>
param(
    [string]$VendorDir = (Join-Path $env:USERPROFILE ".skills-vendor"),
    [string[]]$Only,
    [switch]$Force,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$manifestPath = Join-Path $VendorDir ".vendor.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)

if (-not (Test-Path $manifestPath)) {
    Write-Host "找不到清单文件: $manifestPath" -ForegroundColor Red
    Write-Host "请先手动建立 vendor 目录并写入 .vendor.json（格式见 README）。" -ForegroundColor Yellow
    exit 1
}

$manifest = [System.IO.File]::ReadAllText($manifestPath, $utf8NoBom) | ConvertFrom-Json

# 只支持新结构：顶层必须有 sources。
if (-not $manifest.PSObject.Properties['sources']) {
    Write-Host "清单格式过旧：缺少顶层 sources。" -ForegroundColor Red
    Write-Host "请按下面结构改写 $manifestPath ：" -ForegroundColor Yellow
    Write-Host '  { "sources": { "owner/repo": { "repo", "branch", "upstreamCommit", "syncedAt", "skills" } } }' -ForegroundColor DarkGray
    exit 1
}

# 选出本次要处理的上游。
$sourceKeys = @($manifest.sources.PSObject.Properties.Name)
if ($Only) {
    foreach ($want in $Only) {
        if ($sourceKeys -notcontains $want) {
            Write-Host "未知的上游: $want（可用的：$($sourceKeys -join ', ')）" -ForegroundColor Red
            exit 1
        }
    }
    $sourceKeys = @($Only)
}

if (-not $sourceKeys) {
    Write-Host "清单里没有任何上游。" -ForegroundColor Yellow
    exit 1
}

Write-Host "vendor: $VendorDir"
Write-Host "上游:   $($sourceKeys -join ', ')"
Write-Host ""

# 把某个 skill 目录下以 "." 开头的隐藏文件按相对路径收集起来。
# 这些是本机运行时状态，同步时必须先备份、后还原。
function Get-DotFiles {
    param([string]$Root)
    if (-not (Test-Path $Root)) { return @() }
    return @(Get-ChildItem $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name.StartsWith('.') } |
        ForEach-Object { $_.FullName.Substring($Root.Length).TrimStart('\') })
}

$totalCopied = 0
$bootstrapNeeded = $false

foreach ($key in $sourceKeys) {
    $src = $manifest.sources.$key
    $branch = if ($src.branch) { $src.branch } else { "main" }
    $skillNames = @($src.skills.PSObject.Properties.Name)

    Write-Host "== $key" -ForegroundColor Magenta
    Write-Host "   repo: $($src.repo) ($branch)"

    # --- 1. 克隆上游到临时目录 ---
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("vendor-sync-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    try {
        git clone --depth 1 --branch $branch -q $src.repo $tmp 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "   克隆失败，请检查网络或上游地址。跳过该上游。" -ForegroundColor Red
            continue
        }
        $newSha = (git -C $tmp rev-parse HEAD).Trim()
        $oldSha = $src.upstreamCommit
        Write-Host "   commit: $($newSha.Substring(0,8))"

        if ($newSha -eq $oldSha -and -not $Force) {
            Write-Host "   与上次同步相同，无需更新。" -ForegroundColor Green
            Write-Host ""
            continue
        }

        # --- 2. 检查本地改动（排除隐藏文件，它们是本机状态） ---
        $modified = @()
        foreach ($name in $skillNames) {
            $rel = $src.skills.$name
            $upstreamPath = Join-Path $tmp $rel
            $localPath = Join-Path $VendorDir $name
            if (-not (Test-Path $upstreamPath)) {
                Write-Host "   ! 上游已不存在: $name ($rel)" -ForegroundColor Yellow
                continue
            }
            if (-not (Test-Path $localPath)) { continue }

            $upFiles = Get-ChildItem $upstreamPath -Recurse -File -Force |
                Where-Object { -not $_.Name.StartsWith('.') } |
                ForEach-Object { $_.FullName.Substring($upstreamPath.Length).TrimStart('\') }
            foreach ($f in $upFiles) {
                $uf = Join-Path $upstreamPath $f
                $lf = Join-Path $localPath $f
                if (-not (Test-Path $lf)) { $modified += "$name/$f (上游新增)"; continue }
                if ((Get-FileHash $uf).Hash -ne (Get-FileHash $lf).Hash) { $modified += "$name/$f" }
            }
        }

        if ($modified.Count -gt 0 -and -not $Force) {
            Write-Host ""
            Write-Host "! 以下 $($modified.Count) 个文件与上游不同，同步后本地改动将丢失：" -ForegroundColor Yellow
            $modified | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
            Write-Host ""
            $answer = Read-Host "继续覆盖？(y/N)"
            if ($answer -notmatch '^[yY]') {
                Write-Host "已取消，该上游未改动。" -ForegroundColor Cyan
                Write-Host ""
                continue
            }
        }

        # --- 3. 备份隐藏文件 -> 摊平复制 -> 还原隐藏文件 ---
        Write-Host ""
        Write-Host "   同步 skill..." -ForegroundColor Cyan
        $count = 0
        foreach ($name in $skillNames) {
            $rel = $src.skills.$name
            $upstreamPath = Join-Path $tmp $rel
            $localPath = Join-Path $VendorDir $name
            if (-not (Test-Path $upstreamPath)) { continue }

            # 3a. 备份本机隐藏文件
            $dotFiles = Get-DotFiles $localPath
            $backup = @{}
            foreach ($d in $dotFiles) {
                $backup[$d] = [System.IO.File]::ReadAllBytes((Join-Path $localPath $d))
            }

            # 3b. 整目录替换
            if (Test-Path $localPath) { Remove-Item $localPath -Recurse -Force }
            Copy-Item $upstreamPath $localPath -Recurse -Force

            # 3c. 还原隐藏文件
            foreach ($d in $backup.Keys) {
                $dest = Join-Path $localPath $d
                $parent = Split-Path $dest -Parent
                if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
                [System.IO.File]::WriteAllBytes($dest, $backup[$d])
                Write-Host "     ~ 保留运行时文件 $name/$d" -ForegroundColor DarkGray
            }

            Write-Host "     + $name" -ForegroundColor Green
            $count++
        }

        # --- 4. 回写该上游的同步状态 ---
        $src.upstreamCommit = $newSha
        $src.syncedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        $totalCopied += $count
        $bootstrapNeeded = $true
        Write-Host "   完成，$count 个 skill。" -ForegroundColor Green
        Write-Host ""
    }
    finally {
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

# 统一写回清单（BOM 与原文件一致）。
$json = $manifest | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($manifestPath, $json, $utf8Bom)

if (-not $SkipBootstrap) {
    Write-Host "-> 重建链接..." -ForegroundColor Cyan
    & (Join-Path $repo "bootstrap.ps1")
}
else {
    Write-Host "（已跳过重建链接；如需生效请手动运行 bootstrap.ps1）" -ForegroundColor DarkGray
}
