param(
    [switch]$CiMode,
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExePath = Join-Path $ScriptRoot "AI Music Downloader.exe"
$ManifestPath = Join-Path $ScriptRoot "VERSION_MANIFEST.json"
$DataDir = Join-Path $ScriptRoot "data"
$DownloadsDir = Join-Path $ScriptRoot "downloads"
$StartedAt = [DateTime]::UtcNow
$Checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $Checks.Add([ordered]@{ name = $Name; passed = $Passed; detail = $Detail }) | Out-Null
    if ($Passed) {
        Write-Host "[OK] $Name - $Detail"
    }
    else {
        Write-Host "[GAGAL] $Name - $Detail" -ForegroundColor Red
    }
}

function Assert-File {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-Check $Label $false "File tidak ditemukan: $Path"
        throw "$Label tidak ditemukan."
    }
    Add-Check $Label $true $Path
}

function Invoke-CheckedProcess {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [int]$TimeoutSeconds = 120
    )
    $Process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        throw "Timeout menjalankan $FilePath"
    }
    if ($Process.ExitCode -ne 0) {
        throw "Process gagal exit code $($Process.ExitCode): $FilePath"
    }
}

function Get-IsElevated {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-WindowsInfo {
    $Caption = "Windows"
    $Version = [Environment]::OSVersion.Version.ToString()
    try {
        $Os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        if ($Os.Caption) { $Caption = [string]$Os.Caption }
        if ($Os.Version) { $Version = [string]$Os.Version }
    }
    catch {}
    return [ordered]@{ caption = $Caption; version = $Version }
}

function Verify-HashFromManifest {
    param([string]$RelativePath, [string]$ExpectedHash, [string]$Label)
    $Target = Join-Path $ScriptRoot $RelativePath
    Assert-File $Target $Label
    $Actual = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
    $Expected = $ExpectedHash.Trim().ToLowerInvariant()
    $Passed = ($Actual -eq $Expected)
    Add-Check "$Label SHA-256" $Passed "expected=$Expected actual=$Actual"
    if (-not $Passed) {
        throw "$Label checksum tidak cocok dengan VERSION_MANIFEST.json"
    }
}

$Result = [ordered]@{
    schema_version = 1
    app = "AI Music Downloader"
    started_at_utc = $StartedAt.ToString("o")
    finished_at_utc = $null
    ci_mode = [bool]$CiMode
    windows = $null
    elevated = $null
    manifest_git_sha = $null
    automated_passed = $false
    checks = $Checks
    manual_steps_remaining = @(
        "Buka AI Music Downloader.exe dan pastikan GUI tampil normal.",
        "Masukkan satu media yang memang Anda berhak/diizinkan unduh lalu selesaikan satu download nyata.",
        "Tutup dan buka kembali aplikasi; pastikan antrean/riwayat/pengaturan tetap terbaca."
    )
}

try {
    if ($env:OS -ne "Windows_NT") {
        Add-Check "Sistem operasi Windows" $false "Script ini hanya untuk Windows."
        throw "Bukan Windows."
    }

    $WindowsInfo = Get-WindowsInfo
    $Result.windows = $WindowsInfo
    $VersionParts = ([string]$WindowsInfo.version).Split('.')
    $BuildNumber = 0
    if ($VersionParts.Count -ge 3) { [void][int]::TryParse($VersionParts[2], [ref]$BuildNumber) }
    $IsWindows11 = (($WindowsInfo.caption -notmatch "Server") -and (($WindowsInfo.caption -match "Windows 11") -or ($BuildNumber -ge 22000)))
    if ($CiMode) {
        Add-Check "Windows 11 fisik" $true "CI mode: pemeriksaan edisi fisik dilewati; host=$($WindowsInfo.caption) $($WindowsInfo.version)"
    }
    else {
        Add-Check "Windows 11 fisik" $IsWindows11 "$($WindowsInfo.caption) $($WindowsInfo.version)"
        if (-not $IsWindows11) { throw "Acceptance rilis stabil wajib dijalankan pada Windows 11 fisik." }
    }

    $Elevated = Get-IsElevated
    $Result.elevated = $Elevated
    if ($CiMode) {
        Add-Check "User non-admin" $true "CI mode: status elevated=$Elevated dicatat tetapi tidak menggagalkan run."
    }
    else {
        if ($Elevated) { $AdminDetail = "PowerShell berjalan elevated/admin." } else { $AdminDetail = "Berjalan sebagai user standar/non-elevated." }
        Add-Check "User non-admin" (-not $Elevated) $AdminDetail
        if ($Elevated) { throw "Jalankan UJI_WINDOWS_11.bat sebagai user biasa, jangan Run as administrator." }
    }

    Assert-File $ExePath "Executable aplikasi"
    Assert-File $ManifestPath "VERSION_MANIFEST.json"
    if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }
    if (-not (Test-Path -LiteralPath $DownloadsDir -PathType Container)) { New-Item -ItemType Directory -Path $DownloadsDir | Out-Null }

    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    $Result.manifest_git_sha = [string]$Manifest.git_sha
    Add-Check "Manifest Git SHA" ([bool]$Manifest.git_sha) ([string]$Manifest.git_sha)

    Verify-HashFromManifest "tools\ffmpeg.exe" ([string]$Manifest.tools.ffmpeg.ffmpeg_sha256) "FFmpeg portable"
    Verify-HashFromManifest "tools\ffprobe.exe" ([string]$Manifest.tools.ffmpeg.ffprobe_sha256) "FFprobe portable"
    Verify-HashFromManifest "tools\deno.exe" ([string]$Manifest.tools.deno.exe_sha256) "Deno portable"

    $WriteProbe = Join-Path $DataDir "acceptance-write-test.tmp"
    Set-Content -LiteralPath $WriteProbe -Value "write-ok" -Encoding ASCII
    $WriteOk = ((Get-Content -LiteralPath $WriteProbe -Raw).Trim() -eq "write-ok")
    Remove-Item -LiteralPath $WriteProbe -Force -ErrorAction SilentlyContinue
    Add-Check "Folder data dapat ditulis tanpa admin" $WriteOk $DataDir
    if (-not $WriteOk) { throw "Folder data tidak writable." }

    $OriginalPath = $env:PATH
    try {
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        Invoke-CheckedProcess -FilePath $ExePath -Arguments @("--self-test") -WorkingDirectory $env:TEMP -TimeoutSeconds 120
    }
    finally {
        $env:PATH = $OriginalPath
    }
    Add-Check "Frozen runtime self-test tanpa tool global" $true "EXE lulus --self-test dengan PATH dipersempit."

    $AcceptanceRoot = Join-Path $env:TEMP "AI Music Downloader - Uji Windows 11 日本語"
    $CopyParent = Join-Path $AcceptanceRoot "salinan awal"
    $MovedParent = Join-Path $AcceptanceRoot "dipindah Δ dengan spasi"
    if (Test-Path -LiteralPath $AcceptanceRoot) { Remove-Item -LiteralPath $AcceptanceRoot -Recurse -Force }
    New-Item -ItemType Directory -Path $CopyParent | Out-Null
    New-Item -ItemType Directory -Path $MovedParent | Out-Null

    $CopyPackage = Join-Path $CopyParent "AI-Music-Downloader-Portable"
    Copy-Item -LiteralPath $ScriptRoot -Destination $CopyPackage -Recurse -Force
    $Sentinel = Join-Path $CopyPackage "data\physical-acceptance-sentinel.txt"
    Set-Content -LiteralPath $Sentinel -Value "survives-relocation" -Encoding ASCII

    Move-Item -LiteralPath $CopyPackage -Destination $MovedParent
    $MovedPackage = Join-Path $MovedParent "AI-Music-Downloader-Portable"
    $MovedSentinel = Join-Path $MovedPackage "data\physical-acceptance-sentinel.txt"
    $MovedExe = Join-Path $MovedPackage "AI Music Downloader.exe"
    $RelocationOk = (Test-Path -LiteralPath $MovedSentinel -PathType Leaf) -and (Test-Path -LiteralPath $MovedExe -PathType Leaf)
    Add-Check "Data bertahan setelah seluruh folder portable dipindahkan" $RelocationOk $MovedPackage
    if (-not $RelocationOk) { throw "Relocation package gagal." }

    $OriginalPath = $env:PATH
    try {
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        Invoke-CheckedProcess -FilePath $MovedExe -Arguments @("--self-test") -WorkingDirectory $env:TEMP -TimeoutSeconds 120
    }
    finally {
        $env:PATH = $OriginalPath
    }
    Add-Check "Self-test setelah relocation Unicode/spasi" $true "Paket salinan tetap berfungsi setelah dipindahkan."

    Remove-Item -LiteralPath $AcceptanceRoot -Recurse -Force -ErrorAction SilentlyContinue
    $Result.automated_passed = $true
}
catch {
    Add-Check "Acceptance otomatis keseluruhan" $false $_.Exception.Message
    $Result.automated_passed = $false
}
finally {
    $Result.finished_at_utc = [DateTime]::UtcNow.ToString("o")
    if (-not $OutputPath) {
        if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }
        $OutputPath = Join-Path $DataDir "acceptance-windows11.json"
    }
    $Result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Write-Host ""
    Write-Host "Laporan acceptance otomatis: $OutputPath"
}

if ($Result.automated_passed) {
    Write-Host "WINDOWS11_PHYSICAL_ACCEPTANCE_AUTOMATED_OK" -ForegroundColor Green
    if (-not $CiMode) {
        Write-Host ""
        Write-Host "Tes otomatis lulus. Tiga langkah manual terakhir:" -ForegroundColor Yellow
        foreach ($Step in $Result.manual_steps_remaining) { Write-Host "- $Step" }
    }
    exit 0
}
Write-Host "WINDOWS11_PHYSICAL_ACCEPTANCE_FAILED" -ForegroundColor Red
exit 1
