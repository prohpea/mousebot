# promote-pending.ps1 - copy the C8/C9/C10 deliverables into their real folders.
#
# Why this script exists: this Coder session ran with the sandbox workspace set
# to ...\CVM-colorBot, so writes to the sibling folders
# (...\OBS-xUDP-Plugin and the package root) were denied. The finished v2.1
# files were staged under .bangiao\pending\ instead. Run this once, from the
# CVM-colorBot folder, to publish them:
#
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\promote-pending.ps1
#
# It is safe to run twice (Copy-Item -Force) and it verifies every target.

[CmdletBinding()]
param(
    [switch]$WhatIfOnly
)

$ErrorActionPreference = "Stop"

$botRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path $botRoot -Parent
$stagedPlugin = Join-Path $botRoot ".bangiao\pending\OBS-xUDP-Plugin"
$stagedDoc = Join-Path $botRoot ".bangiao\pending\HUONG_DAN_CAI_DAT.txt"
$livePlugin = Join-Path $packageRoot "OBS-xUDP-Plugin"

$map = @(
    @{ Src = (Join-Path $stagedPlugin "config.json");               Dst = (Join-Path $livePlugin "config.json") },
    @{ Src = (Join-Path $stagedPlugin "cvm_config_optimized.json"); Dst = (Join-Path $livePlugin "cvm_config_optimized.json") },
    @{ Src = (Join-Path $stagedPlugin "install.ps1");               Dst = (Join-Path $livePlugin "install.ps1") },
    @{ Src = (Join-Path $stagedPlugin "HUONG_DAN_SU_DUNG.txt");     Dst = (Join-Path $livePlugin "HUONG_DAN_SU_DUNG.txt") },
    @{ Src = $stagedDoc;                                            Dst = (Join-Path $packageRoot "HUONG_DAN_CAI_DAT.txt") }
)

foreach ($item in $map) {
    if (-not (Test-Path $item.Src)) {
        Write-Host "[ERROR] Thieu file staged: $($item.Src)" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path (Split-Path $item.Dst -Parent))) {
        Write-Host "[ERROR] Thu muc dich khong ton tai: $(Split-Path $item.Dst -Parent)" -ForegroundColor Red
        exit 1
    }
}

foreach ($item in $map) {
    if ($WhatIfOnly) {
        Write-Host "[whatif] $($item.Src)  ->  $($item.Dst)" -ForegroundColor Gray
    } else {
        Copy-Item -LiteralPath $item.Src -Destination $item.Dst -Force
        Write-Host "[ok] $($item.Dst)" -ForegroundColor Green
    }
}

if (-not $WhatIfOnly) {
    # Verify the promoted payload really is v2.1 (parse, do not trust the copy).
    foreach ($name in @("config.json", "cvm_config_optimized.json")) {
        $path = Join-Path $livePlugin $name
        $payload = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($payload.config_schema -ne 5 -or [string]$payload.udp_port -ne "5000") {
            Write-Host "[ERROR] $path khong phai v2.1 sau khi copy" -ForegroundColor Red
            exit 1
        }
        Write-Host "[ok] $name schema=$($payload.config_schema) port=$($payload.udp_port) dpi=$($payload.mouse_dpi)" -ForegroundColor Green
    }

    $ps1 = Join-Path $livePlugin "install.ps1"
    if (Select-String -LiteralPath $ps1 -Pattern "240 FPS" -Quiet) {
        Write-Host "[ERROR] install.ps1 chua chuoi '240 FPS' (test O6 se do)" -ForegroundColor Red
        exit 1
    }
    [scriptblock]::Create((Get-Content -LiteralPath $ps1 -Raw)) | Out-Null
    Write-Host "[ok] install.ps1 parse OK, khong chua '240 FPS'" -ForegroundColor Green

    Write-Host ""
    Write-Host "Promote xong. Chay lai: .\venv\Scripts\python.exe -m unittest tests.test_obs_config_sync -v" -ForegroundColor Cyan
}

exit 0
