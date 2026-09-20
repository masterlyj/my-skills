<#
.SYNOPSIS
    从上游同步第三方 skill 到 vendor 目录，然后重建全部 junction 链接。

.DESCRIPTION
    vendor 目录（默认 ~/.skills-vendor）存放不在本仓库 git 管理内的第三方
    skill，清单记录在同目录的 .vendor.json 里。本脚本：

      1. 读取 .vendor.json，得知要从哪个上游、取哪些 skill；
      2. 把上游仓库浅克隆到临时目录；
      3. 按清单把每个 skill 从上游的桶路径摊平复制到 vendor 根目录；
      4. 调用 bootstrap.ps1 重建各 agent 目录下的 junction。

    覆盖策略：vendor 目录里的内容视为上游快照，同步时直接覆盖。若某个 skill
    的本地内容与上游不同，脚本会列出该文件并停下（除非 -Force）——因为对
    vendor 的本地修改在下次同步时会丢失，值得确认一次。

.PARAMETER VendorDir
    vendor 目录，默认 ~/.skills-vendor。

.PARAMETER Force
    无条件覆盖本地改动，不询问。

.PARAMETER SkipBootstrap
    只同步文件，不重建链接。用于先看差异再决定。

.EXAMPLE
    .\sync-vendor.ps1
    同步上游并重建链接，本地有改动时停下询问。

.EXAMPLE
    .\sync-vendor.ps1 -Force
    无条件覆盖。

.EXAMPLE
    .\sync-vendor.ps1 -SkipBootstrap
    只同步，之后手动跑 bootstrap.ps1。
#>
param(
    [string]$VendorDir = (Join-Path $env:USERPROFILE ".skills-vendor"),
    [switch]$Force,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$manifestPath = Join-Path $VendorDir ".vendor.json"

if (-not (Test-Path $manifestPath)) {
    Write-Host "找不到清单文件: $manifestPath" -ForegroundColor Red
    Write-Host "请先手动建立 vendor 目录并写入 .vendor.json（格式见 README）。" -ForegroundColor Yellow
    exit 1
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$source = $manifest.source
$branch = if ($manifest.branch) { $manifest.branch } else { "main" }

Write-Host "上游:   $source ($branch)"
Write-Host "vendor: $VendorDir"
Write-Host ""

# --- 1. 克隆上游到临时目录 ---
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("vendor-sync-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
try {
    Write-Host "-> 克隆上游..." -ForegroundColor Cyan
    git clone --depth 1 --branch $branch -q $source $tmp 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "克隆失败，请检查网络或上游地址。" -ForegroundColor Red
        exit 1
    }
    $newSha = (git -C $tmp rev-parse HEAD).Trim()
    $oldSha = $manifest.upstreamCommit
    Write-Host "   上游 commit: $($newSha.Substring(0,8))"

    if ($newSha -eq $oldSha -and -not $Force) {
        Write-Host "   与上次同步相同，无需更新。" -ForegroundColor Green
        Write-Host ""
        Write-Host "（如需强制重同步，加 -Force）" -ForegroundColor DarkGray

        # 上游没变就不动 vendor，避免白白覆盖本地改动。
        if (-not $SkipBootstrap) {
            Write-Host ""
            Write-Host "-> 重建链接..." -ForegroundColor Cyan
            & (Join-Path $repo "bootstrap.ps1")
        }
        exit 0
    }

    # --- 2. 检查本地改动 ---
    # vendor 是上游快照，本地改动会在同步时丢失，所以先找出差异。
    $modified = @()
    foreach ($name in $manifest.skills.PSObject.Properties.Name) {
        $rel = $manifest.skills.$name
        $upstreamPath = Join-Path $tmp $rel
        $localPath = Join-Path $VendorDir $name
        if (-not (Test-Path $upstreamPath)) {
            Write-Host "   ! 上游已不存在: $name ($rel)" -ForegroundColor Yellow
            continue
        }
        if (-not (Test-Path $localPath)) { continue }

        # 逐文件比对；上游新增的文件也算差异。
        $upFiles = Get-ChildItem $upstreamPath -Recurse -File |
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
            Write-Host "已取消，vendor 目录未改动。" -ForegroundColor Cyan
            exit 0
        }
    }

    # --- 3. 摊平复制到 vendor ---
    Write-Host ""
    Write-Host "-> 同步 skill..." -ForegroundColor Cyan
    $count = 0
    foreach ($name in $manifest.skills.PSObject.Properties.Name) {
        $rel = $manifest.skills.$name
        $upstreamPath = Join-Path $tmp $rel
        $localPath = Join-Path $VendorDir $name
        if (-not (Test-Path $upstreamPath)) { continue }

        if (Test-Path $localPath) { Remove-Item $localPath -Recurse -Force }
        Copy-Item $upstreamPath $localPath -Recurse -Force
        Write-Host "   + $name"
        $count++
    }

    # --- 4. 更新清单 ---
    $manifest.upstreamCommit = $newSha
    $manifest.syncedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $manifest | ConvertTo-Json -Depth 5 | Set-Content $manifestPath -Encoding utf8
    Write-Host ""
    Write-Host "同步完成，共 $count 个 skill。" -ForegroundColor Green
}
finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}

# --- 5. 重建链接 ---
if (-not $SkipBootstrap) {
    Write-Host ""
    Write-Host "-> 重建链接..." -ForegroundColor Cyan
    & (Join-Path $repo "bootstrap.ps1")
}
