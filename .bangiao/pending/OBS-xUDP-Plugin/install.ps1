# CVM xUDP / VeloNet OBS plugin installer - v2.1 (144 FPS)
# Plan PLAN-20261112-UDP-V21-ZERO-LAG §4.2
#
# What this does:
#   1. Finds OBS Studio (Registry / Uninstall entries / Steam / disks), or asks.
#   2. Copies the plugin + turbojpeg.dll, then verifies the copy.
#   3. Creates the correct-direction UDP firewall rules (idempotent).
#   4. Warns when the VC++ 2015-2022 x64 runtime is missing.
#
# Notes:
#   - Messages are ASCII-only on purpose: the default console code page
#     (cp437/cp1258) would garble Vietnamese diacritics.
#   - Exit codes: 0 = success, 1 = not installed, 2 = installed with warnings.

#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ObsPath = "",
    [switch]$SkipFirewall,
    [switch]$ForceCloseObs,
    [switch]$SkipLocalReceiverRule
)

$ErrorActionPreference = "Stop"
$script:ExitCode = 0

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  CVM xUDP / VeloNet OBS Plugin v2.1 - 144 FPS / Purple" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Cyan

# ----------------------------------------------------------------------
# 0. Administrator check (plugin folder + firewall both need elevation)
# ----------------------------------------------------------------------
function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Host "[ERROR] Can quyen Administrator de copy plugin + tao firewall rule." -ForegroundColor Red
    Write-Host "Chuot phai install.bat -> Run as administrator." -ForegroundColor Yellow
    exit 1
}

# ----------------------------------------------------------------------
# 1. OBS auto-detection
# ----------------------------------------------------------------------
function Resolve-ObsCandidate([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return $null }
    $p = $path.Trim().Trim('"')
    if (-not (Test-Path $p)) { return $null }
    $item = Get-Item $p -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }

    # The user may point at the OBS root, obs64.exe, or bin\64bit\obs64.exe.
    if ($item.PSIsContainer) { $dir = $item.FullName }
    else { $dir = Split-Path $item.FullName -Parent }

    # If we are in ...\bin\64bit, walk back two levels to the OBS root.
    if ($dir -match '(?i)\\bin\\64bit$') {
        $dir = Split-Path (Split-Path $dir -Parent) -Parent
    }

    if (Test-Path (Join-Path $dir "bin\64bit\obs64.exe")) {
        return (Resolve-Path $dir).Path
    }
    return $null
}

function Find-ObsStudio {
    # 1) Registry. Not every OBS build writes this key, so it is one source
    #    among several and we always keep looking after a miss.
    $regKeys = @(
        "HKLM:\SOFTWARE\OBS Studio",
        "HKLM:\SOFTWARE\WOW6432Node\OBS Studio",
        "HKCU:\SOFTWARE\OBS Studio"
    )
    foreach ($key in $regKeys) {
        if (Test-Path $key) {
            $props = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
            if ($null -ne $props) {
                foreach ($name in @("InstallLocation", "InstallDir", "Path")) {
                    $cand = Resolve-ObsCandidate ([string]$props.$name)
                    if ($cand) { return $cand }
                }
            }
        }
    }

    # 2) Uninstall entry (DisplayIcon / InstallLocation).
    $uninstallRoots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($root in $uninstallRoots) {
        if (-not (Test-Path $root)) { continue }
        # foreach (not ForEach-Object) so `return` leaves the FUNCTION.
        $entries = @(Get-ChildItem $root -ErrorAction SilentlyContinue)
        foreach ($entry in $entries) {
            $p = Get-ItemProperty $entry.PSPath -ErrorAction SilentlyContinue
            if ($null -eq $p -or [string]$p.DisplayName -notmatch "OBS Studio") { continue }
            $icon = [string]$p.DisplayIcon
            if ($icon) {
                $exe = ($icon -split ",")[0].Trim('"')
                $cand = Resolve-ObsCandidate (Split-Path $exe -Parent)
                if ($cand) { return $cand }
            }
            $cand = Resolve-ObsCandidate ([string]$p.InstallLocation)
            if ($cand) { return $cand }
        }
    }

    # 3) Steam library (libraryfolders.vdf lists extra drives).
    $steamKeys = @("HKCU:\SOFTWARE\Valve\Steam", "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam")
    foreach ($key in $steamKeys) {
        if (-not (Test-Path $key)) { continue }
        $steamProps = Get-ItemProperty $key -ErrorAction SilentlyContinue
        $steamPath = if ($null -ne $steamProps) { [string]$steamProps.SteamPath } else { "" }
        if (-not $steamPath) { continue }
        $steamPath = $steamPath -replace "/", "\"
        $vdf = Join-Path $steamPath "steamapps\libraryfolders.vdf"
        $libraries = @($steamPath)
        if (Test-Path $vdf) {
            $content = Get-Content $vdf -Raw
            foreach ($m in [regex]::Matches($content, '"path"\s+"([^"]+)"')) {
                $libraries += ($m.Groups[1].Value -replace "\\\\", "\")
            }
        }
        foreach ($lib in ($libraries | Select-Object -Unique)) {
            $cand = Resolve-ObsCandidate (Join-Path $lib "steamapps\common\OBS Studio")
            if ($cand) { return $cand }
        }
    }

    # 4) Disk fallbacks (skip empty env vars so Join-Path cannot throw).
    $fallbacks = @()
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($base) { $fallbacks += (Join-Path $base "obs-studio") }
    }
    $fallbacks += @(
        "C:\Program Files\obs-studio",
        "D:\Program Files\obs-studio",
        "E:\Program Files\obs-studio",
        "D:\obs-studio",
        "E:\obs-studio"
    )
    foreach ($path in $fallbacks) {
        $cand = Resolve-ObsCandidate $path
        if ($cand) { return $cand }
    }
    return $null
}

$obsDir = $null
if (-not [string]::IsNullOrWhiteSpace($ObsPath)) {
    $obsDir = Resolve-ObsCandidate $ObsPath
    if (-not $obsDir) {
        Write-Host "[ERROR] -ObsPath khong hop le: $ObsPath" -ForegroundColor Red
        Write-Host "        Can tro toi thu muc chua bin\64bit\obs64.exe" -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "[1/6] Tim OBS Studio..." -ForegroundColor Gray
    $obsDir = Find-ObsStudio
    for ($attempt = 1; $attempt -le 3 -and -not $obsDir; $attempt++) {
        Write-Host "[!] Khong tim thay OBS Studio tu dong." -ForegroundColor Yellow
        # NOT $input: that is a PowerShell automatic variable.
        $userPath = Read-Host "Nhap duong dan OBS Studio (thu muc chua bin\64bit\obs64.exe)"
        if ([string]::IsNullOrWhiteSpace($userPath)) { continue }
        $cand = Resolve-ObsCandidate $userPath
        if ($cand) { $obsDir = $cand; break }
        Write-Host "[!] Khong hop le: $userPath" -ForegroundColor Yellow
    }
    if (-not $obsDir) {
        Write-Host "[ERROR] Khong tim thay OBS Studio. Cai OBS 64-bit hoac chay:" -ForegroundColor Red
        Write-Host "        .\install.ps1 -ObsPath 'D:\obs-studio'" -ForegroundColor Yellow
        exit 1
    }
}
Write-Host "[OK] OBS Studio: $obsDir" -ForegroundColor Green

# ----------------------------------------------------------------------
# 2. Verify the payload before touching the OBS install
# ----------------------------------------------------------------------
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$required = @(
    "obs-plugins\64bit\obs-color-correction.dll",
    "bin\64bit\turbojpeg.dll"
)
foreach ($rel in $required) {
    if (-not (Test-Path (Join-Path $scriptDir $rel))) {
        Write-Host "[ERROR] Thieu file nguon: $rel" -ForegroundColor Red
        Write-Host "        Chay script tu thu muc OBS-xUDP-Plugin da giai nen day du." -ForegroundColor Yellow
        exit 1
    }
}

# ----------------------------------------------------------------------
# 3. Close OBS (a loaded DLL can never be replaced in place)
# ----------------------------------------------------------------------
$obs = Get-Process -Name "obs64" -ErrorAction SilentlyContinue
if ($obs) {
    if (-not $ForceCloseObs) {
        Write-Host "[!] OBS dang chay. Dong OBS se NGAT stream/ban ghi dang chay" -ForegroundColor Yellow
        Write-Host "    (ban ghi co the bi hong)." -ForegroundColor Yellow
        $answer = Read-Host "Dong OBS de cai plugin? (Y/N)"
        if ($answer -notmatch "^(y|yes)$") {
            Write-Host "[!] Huy cai dat. Hay dong OBS roi chay lai." -ForegroundColor Yellow
            exit 1
        }
    }
    $obs | Stop-Process -Force
    Start-Sleep -Milliseconds 800
}

# ----------------------------------------------------------------------
# 4. Copy + verify
# ----------------------------------------------------------------------
Write-Host "[2/6] Chep plugin vao OBS Studio..." -ForegroundColor Gray
Copy-Item "$scriptDir\obs-plugins\64bit\*" "$obsDir\obs-plugins\64bit\" -Force -Recurse
Copy-Item "$scriptDir\bin\64bit\*" "$obsDir\bin\64bit\" -Force -Recurse

# TurboJPEG next to the receiver's default DLL search path.
$turboDir = "C:\libjpeg-turbo64\bin"
New-Item -ItemType Directory -Path $turboDir -Force | Out-Null
Copy-Item "$scriptDir\bin\64bit\turbojpeg.dll" "$turboDir\turbojpeg.dll" -Force

$installedDll = Join-Path $obsDir "obs-plugins\64bit\obs-color-correction.dll"
if (-not (Test-Path $installedDll)) {
    Write-Host "[ERROR] Copy that bai: $installedDll" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Plugin: obs-color-correction.dll" -ForegroundColor Green
Write-Host "[OK] Decoder: turbojpeg.dll ($turboDir)" -ForegroundColor Green

# ----------------------------------------------------------------------
# 5. Firewall - correct direction, idempotent
# ----------------------------------------------------------------------
$obsExe = Join-Path $obsDir "bin\64bit\obs64.exe"
if (-not (Test-Path $obsExe)) {
    Write-Host "[ERROR] Khong tim thay obs64.exe: $obsExe" -ForegroundColor Red
    exit 1
}

function Set-CvmFirewallRule {
    param(
        [string]$Name,
        [string]$Direction,      # Inbound | Outbound
        [string]$Protocol = "UDP",
        [int]$LocalPort = 0,
        [int]$RemotePort = 0,
        [string]$Program = "",
        [string]$Description = ""
    )
    # Remove first: running the installer twice must not duplicate rules.
    Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue

    $params = @{
        DisplayName = $Name
        Direction   = $Direction
        Protocol    = $Protocol
        Action      = "Allow"
        Profile     = "Any"
        Description = $Description
        Enabled     = "True"
    }
    if ($LocalPort -gt 0) { $params.LocalPort = $LocalPort }
    if ($RemotePort -gt 0) { $params.RemotePort = $RemotePort }
    if ($Program) { $params.Program = $Program }
    New-NetFirewallRule @params | Out-Null
}

Write-Host "[3/6] Cau hinh Windows Firewall..." -ForegroundColor Gray
if (-not $SkipFirewall) {
    try {
        # OBS sends from an ephemeral source port to PC2:5000, so the outbound
        # rule must key on RemotePort 5000 - LocalPort 5000 is meaningless here.
        Set-CvmFirewallRule -Name "CVM xUDP - OBS Studio UDP In" `
            -Direction Inbound -Protocol UDP -Program $obsExe `
            -Description "OBS Studio nhan UDP (plugin/websocket/beep)"
        Set-CvmFirewallRule -Name "CVM xUDP - OBS Studio UDP Out" `
            -Direction Outbound -Protocol UDP -Program $obsExe `
            -Description "OBS Studio gui stream xUDP toi may 2"
        Set-CvmFirewallRule -Name "CVM xUDP - Beep 4455 In" `
            -Direction Inbound -Protocol UDP -LocalPort 4455 `
            -Description "Nhan tin hieu toggle tu bot (UDP 4455, khong phai TCP)"
        Set-CvmFirewallRule -Name "CVM xUDP - Stream 5000 Out" `
            -Direction Outbound -Protocol UDP -RemotePort 5000 `
            -Description "Gui stream toi may 2 cong 5000"

        if (-not $SkipLocalReceiverRule) {
            Set-CvmFirewallRule -Name "CVM xUDP - Stream 5000 In" `
                -Direction Inbound -Protocol UDP -LocalPort 5000 `
                -Description "Nhan stream tren may nay (can khi bot chay cung may)"
        }
        Write-Host "[OK] Firewall: UDP 4455 In / UDP 5000 Out (RemotePort) / UDP 5000 In" -ForegroundColor Green
    } catch {
        Write-Host "[!] Khong tao duoc firewall rule: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "    Chay PowerShell as Administrator hoac tu tao rule theo HUONG_DAN_SU_DUNG.txt" -ForegroundColor Yellow
        $script:ExitCode = 2
    }
} else {
    Write-Host "[i] Bo qua firewall (-SkipFirewall). Lenh thu cong:" -ForegroundColor Gray
    Write-Host "    New-NetFirewallRule -DisplayName 'CVM xUDP - Beep 4455 In' -Direction Inbound -Protocol UDP -LocalPort 4455 -Action Allow"
    Write-Host "    New-NetFirewallRule -DisplayName 'CVM xUDP - Stream 5000 Out' -Direction Outbound -Protocol UDP -RemotePort 5000 -Action Allow"
    Write-Host "    New-NetFirewallRule -DisplayName 'CVM xUDP - Stream 5000 In' -Direction Inbound -Protocol UDP -LocalPort 5000 -Action Allow"
}

# ----------------------------------------------------------------------
# 6. VC++ 2015-2022 x64 runtime (warn only, never block the install)
# ----------------------------------------------------------------------
function Test-VCRedistX64 {
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    )
    foreach ($key in $keys) {
        if (Test-Path $key) {
            $p = Get-ItemProperty $key -ErrorAction SilentlyContinue
            if ($null -ne $p -and $p.Installed -eq 1) { return $true }
        }
    }
    return $false
}

Write-Host "[4/6] Kiem tra VC++ 2015-2022 x64..." -ForegroundColor Gray
$vcOk = Test-VCRedistX64
if (-not $vcOk) {
    Write-Host "[!] THIEU VC++ 2015-2022 x64 (plugin se khong load duoc)." -ForegroundColor Yellow
    Write-Host "    Tai: https://aka.ms/vs/17/release/vc_redist.x64.exe" -ForegroundColor Yellow
    Write-Host "    (Script khong tu tai: may co the dang offline.)" -ForegroundColor Gray
    $script:ExitCode = 2
}

# ----------------------------------------------------------------------
# 7. Summary
# ----------------------------------------------------------------------
$vcText = if ($vcOk) { "OK" } else { "THIEU" }
Write-Host "[5/6] Hoan tat." -ForegroundColor Gray
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  CVM xUDP / VeloNet OBS Plugin v2.1 - 144 FPS / Purple" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "[OK] OBS Studio : $obsDir" -ForegroundColor Green
Write-Host "[OK] Plugin     : obs-color-correction.dll" -ForegroundColor Green
Write-Host "[OK] Decoder    : turbojpeg.dll ($turboDir)" -ForegroundColor Green
if ($SkipFirewall) {
    Write-Host "[i]  Firewall   : da bo qua (-SkipFirewall)" -ForegroundColor Gray
} else {
    Write-Host "[OK] Firewall   : UDP 4455 In - UDP 5000 Out (RemotePort) - UDP 5000 In" -ForegroundColor Green
}
Write-Host "[!]  VC++ 2015-2022 x64: $vcText" -ForegroundColor $(if ($vcOk) { "Green" } else { "Yellow" })
Write-Host "----------------------------------------------------------------"
Write-Host "Buoc tiep theo:"
Write-Host " 1. Mo OBS -> Settings -> Video: FPS = 144"
Write-Host " 2. Filter Color Correction: 320x320, JPEG 80-85,"
Write-Host "    Target IP = IP cua may 2, Target Port = 5000"
Write-Host " 3. Tren may 2: chay CVM-colorBot, Capture = UDP,"
Write-Host "    IP = 0.0.0.0, Port = 5000"
Write-Host " 4. Bat/tat aim de nghe beep (UDP 4455) tren tai nghe PC1."
Write-Host "================================================================" -ForegroundColor Cyan

Write-Host "[6/6] Exit code: $($script:ExitCode)" -ForegroundColor Gray
exit $script:ExitCode
