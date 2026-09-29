$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"
$ReleaseDir = Join-Path $Root "release"
$PackageDir = Join-Path $ReleaseDir "AI-Music-Downloader-Portable"
$ZipPath = Join-Path $ReleaseDir "AI-Music-Downloader-Portable.zip"
$ZipChecksumPath = "$ZipPath.sha256"
$ToolPinsPath = Join-Path $Root "release-tools.json"
$NoticesPath = Join-Path $Root "THIRD_PARTY_NOTICES.txt"

if (-not (Test-Path $ToolPinsPath)) {
    throw "release-tools.json tidak ditemukan."
}
$ToolPins = Get-Content $ToolPinsPath -Raw | ConvertFrom-Json
$SelfTestTimeoutSeconds = [int]$ToolPins.self_test_timeout_seconds

function Assert-Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $Actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $ExpectedValue = $Expected.Trim().ToLowerInvariant()
    if ($Actual -ne $ExpectedValue) {
        throw "$Label checksum tidak cocok. Expected=$ExpectedValue Actual=$Actual"
    }
    Write-Host "$Label`_SHA256_OK: $Actual"
    return $Actual
}

function Read-ChecksumFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Text = Get-Content $Path -Raw
    $Match = [regex]::Match($Text, '(?i)\b[a-f0-9]{64}\b')
    if (-not $Match.Success) {
        throw "Checksum SHA-256 tidak dapat dibaca: $Path"
    }
    return $Match.Value.ToLowerInvariant()
}

function Invoke-ProcessWithTimeout {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [string]$WorkingDirectory = ""
    )
    $Args = @{
        FilePath = $FilePath
        ArgumentList = $ArgumentList
        PassThru = $true
    }
    if ($WorkingDirectory) {
        $Args.WorkingDirectory = $WorkingDirectory
    }
    $Process = Start-Process @Args
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        throw "Process timeout setelah $TimeoutSeconds detik: $FilePath"
    }
    if ($Process.ExitCode -ne 0) {
        throw "Process gagal dengan exit code $($Process.ExitCode): $FilePath"
    }
}

Write-Host "== AI Music Downloader: reproducible portable Windows build =="
Write-Host "Pinned FFmpeg: $($ToolPins.ffmpeg.version)"
Write-Host "Pinned Deno   : $($ToolPins.deno.version)"

foreach ($Path in @($BuildDir, $DistDir, $ReleaseDir)) {
    if (Test-Path $Path) {
        Remove-Item $Path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

Write-Host "[1/9] Building one-folder EXE with pinned PyInstaller environment..."
& python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "AI Music Downloader" `
    --collect-all spotdl `
    --collect-all yt_dlp `
    --collect-all yt_dlp_ejs `
    --copy-metadata yt-dlp-ejs `
    --collect-all pykakasi `
    --hidden-import spotdl.types.song `
    --hidden-import spotdl.types.album `
    --hidden-import spotdl.types.playlist `
    --distpath $DistDir `
    --workpath (Join-Path $BuildDir "pyinstaller") `
    --specpath $BuildDir `
    (Join-Path $Root "main.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller gagal dengan exit code $LASTEXITCODE"
}

$BuiltApp = Join-Path $DistDir "AI Music Downloader"
$BuiltExe = Join-Path $BuiltApp "AI Music Downloader.exe"
if (-not (Test-Path $BuiltExe)) {
    throw "Hasil build EXE tidak ditemukan."
}

Write-Host "[2/9] Preparing portable multi-file folder..."
New-Item -ItemType Directory -Path $PackageDir | Out-Null
Copy-Item (Join-Path $BuiltApp "*") $PackageDir -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $PackageDir "tools") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "downloads") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "data") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "release-info") | Out-Null
Copy-Item (Join-Path $Root "config.example.json") (Join-Path $PackageDir "config.example.json") -Force
Copy-Item $ToolPinsPath (Join-Path $PackageDir "release-info\release-tools.json") -Force
Copy-Item (Join-Path $Root "requirements.txt") (Join-Path $PackageDir "release-info\requirements.txt") -Force
Copy-Item (Join-Path $Root "constraints.lock.txt") (Join-Path $PackageDir "release-info\constraints.lock.txt") -Force
Copy-Item (Join-Path $Root "requirements-build.txt") (Join-Path $PackageDir "release-info\requirements-build.txt") -Force
Copy-Item $NoticesPath (Join-Path $PackageDir "THIRD_PARTY_NOTICES.txt") -Force

$PykakasiDb = Join-Path $PackageDir "_internal\pykakasi\data\kanwadict4.db"
if (-not (Test-Path $PykakasiDb)) {
    throw "Data runtime pykakasi tidak ikut terbundle: $PykakasiDb"
}

Write-Host "[3/9] Downloading pinned FFmpeg and verifying SHA-256..."
$FfmpegZip = Join-Path $BuildDir "ffmpeg.zip"
$FfmpegSum = Join-Path $BuildDir "ffmpeg.zip.sha256"
$FfmpegExtract = Join-Path $BuildDir "ffmpeg"
Invoke-WebRequest -Uri $ToolPins.ffmpeg.url -OutFile $FfmpegZip -UseBasicParsing
Invoke-WebRequest -Uri $ToolPins.ffmpeg.checksum_url -OutFile $FfmpegSum -UseBasicParsing
$PublishedFfmpegHash = Read-ChecksumFile $FfmpegSum
$PinnedFfmpegHash = $ToolPins.ffmpeg.sha256.ToLowerInvariant()
if ($PublishedFfmpegHash -ne $PinnedFfmpegHash) {
    throw "Checksum FFmpeg upstream berubah dari pin. Pinned=$PinnedFfmpegHash Upstream=$PublishedFfmpegHash"
}
$ActualFfmpegHash = Assert-Sha256 $FfmpegZip $PinnedFfmpegHash "FFMPEG_ARCHIVE"
Expand-Archive -Path $FfmpegZip -DestinationPath $FfmpegExtract -Force

$FfmpegExe = Get-ChildItem $FfmpegExtract -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
$FfprobeExe = Get-ChildItem $FfmpegExtract -Filter "ffprobe.exe" -Recurse | Select-Object -First 1
if (-not $FfmpegExe -or -not $FfprobeExe) {
    throw "Paket FFmpeg wajib memuat ffmpeg.exe dan ffprobe.exe."
}
$PortableFfmpeg = Join-Path $PackageDir "tools\ffmpeg.exe"
$PortableFfprobe = Join-Path $PackageDir "tools\ffprobe.exe"
Copy-Item $FfmpegExe.FullName $PortableFfmpeg -Force
Copy-Item $FfprobeExe.FullName $PortableFfprobe -Force

Write-Host "[4/9] Downloading pinned Deno and verifying published + pinned SHA-256..."
$DenoZip = Join-Path $BuildDir "deno.zip"
$DenoSum = Join-Path $BuildDir "deno.zip.sha256sum"
$DenoExtract = Join-Path $BuildDir "deno"
Invoke-WebRequest -Uri $ToolPins.deno.url -OutFile $DenoZip -UseBasicParsing
Invoke-WebRequest -Uri $ToolPins.deno.checksum_url -OutFile $DenoSum -UseBasicParsing
$PublishedDenoHash = Read-ChecksumFile $DenoSum
$PinnedDenoHash = $ToolPins.deno.sha256.ToLowerInvariant()
if ($PublishedDenoHash -ne $PinnedDenoHash) {
    throw "Checksum Deno upstream berubah dari pin. Pinned=$PinnedDenoHash Upstream=$PublishedDenoHash"
}
$ActualDenoHash = Assert-Sha256 $DenoZip $PinnedDenoHash "DENO_ARCHIVE"
Expand-Archive -Path $DenoZip -DestinationPath $DenoExtract -Force
$DenoExe = Get-ChildItem $DenoExtract -Filter "deno.exe" -Recurse | Select-Object -First 1
if (-not $DenoExe) {
    throw "deno.exe tidak ditemukan di paket Deno."
}
$PortableDeno = Join-Path $PackageDir "tools\deno.exe"
Copy-Item $DenoExe.FullName $PortableDeno -Force

Write-Host "[5/9] Running production frozen self-test (versions + local audio conversion)..."
$PortableExe = Join-Path $PackageDir "AI Music Downloader.exe"
Invoke-ProcessWithTimeout `
    -FilePath $PortableExe `
    -ArgumentList @("--self-test") `
    -TimeoutSeconds $SelfTestTimeoutSeconds `
    -WorkingDirectory $PackageDir
Write-Host "FROZEN_RUNTIME_SELF_TEST_OK"

Write-Host "[6/9] Writing release manifest, notices, README, and verifying package layout..."
$GitSha = (& git -C $Root rev-parse HEAD).Trim()
$PythonVersion = (& python -c "import platform; print(platform.python_version())").Trim()
$PackageNames = @(
    "PySide6",
    "yt-dlp",
    "yt-dlp-ejs",
    "spotdl",
    "mutagen",
    "pyinstaller",
    "pyinstaller-hooks-contrib"
)
$PackageVersions = [ordered]@{}
foreach ($PackageName in $PackageNames) {
    $Value = (& python -c "from importlib.metadata import version; print(version('$PackageName'))").Trim()
    $PackageVersions[$PackageName] = $Value
}

$SourceHashes = [ordered]@{}
foreach ($SourceFile in @("requirements.txt", "constraints.lock.txt", "requirements-build.txt", "release-tools.json")) {
    $SourcePath = Join-Path $Root $SourceFile
    $SourceHashes[$SourceFile] = (Get-FileHash $SourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
}

$Manifest = [ordered]@{
    schema_version = 1
    app = "AI Music Downloader"
    git_sha = $GitSha
    built_at_utc = [DateTime]::UtcNow.ToString("o")
    python = $PythonVersion
    architecture = $env:PROCESSOR_ARCHITECTURE
    packages = $PackageVersions
    tools = [ordered]@{
        ffmpeg = [ordered]@{
            version = $ToolPins.ffmpeg.version
            archive_sha256 = $ActualFfmpegHash
            ffmpeg_sha256 = (Get-FileHash $PortableFfmpeg -Algorithm SHA256).Hash.ToLowerInvariant()
            ffprobe_sha256 = (Get-FileHash $PortableFfprobe -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        deno = [ordered]@{
            version = $ToolPins.deno.version
            archive_sha256 = $ActualDenoHash
            exe_sha256 = (Get-FileHash $PortableDeno -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    source_lock_sha256 = $SourceHashes
    portable_layout = @(
        "AI Music Downloader.exe",
        "_internal/",
        "tools/ffmpeg.exe",
        "tools/ffprobe.exe",
        "tools/deno.exe",
        "data/",
        "downloads/",
        "release-info/",
        "THIRD_PARTY_NOTICES.txt",
        "README_PORTABLE.txt"
    )
}
$ManifestPath = Join-Path $PackageDir "VERSION_MANIFEST.json"
$Manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $ManifestPath -Encoding UTF8

$PortableReadme = @"
AI MUSIC DOWNLOADER - PORTABLE WINDOWS
======================================

Cara menjalankan:
1. Extract SELURUH folder dari ZIP.
2. Jalankan: AI Music Downloader.exe
3. Tidak perlu installer, Python, FFmpeg, ffprobe, atau Deno terpasang di Windows.
4. Jangan memindahkan EXE sendirian; _internal, tools, data, dan file pendamping harus tetap dalam satu folder portable.

Folder penting:
- downloads\  : hasil download default
- data\       : antrean, riwayat, data lokal, dan key terenkripsi bila mode DPAPI digunakan
- tools\      : FFmpeg, ffprobe, dan Deno portable yang sudah diverifikasi checksum-nya
- config.json : dibuat otomatis saat pengaturan disimpan

Mode audio:
- Original / Best Audio: menyimpan stream audio terbaik tanpa transcoding tambahan.
- M4A: memprioritaskan source M4A bila tersedia.
- MP3: menggunakan FFmpeg portable di tools\.

YouTube:
Deno dan yt-dlp-ejs dibundel agar yt-dlp dapat menangani JavaScript challenge tanpa instalasi runtime sistem.

Spotify:
Spotify hanya digunakan untuk membaca metadata track/album/playlist. Audio Spotify/DRM tidak diakses.

UPDATE VERSI PORTABLE DENGAN DATA TETAP AMAN
--------------------------------------------
1. Tutup AI Music Downloader sepenuhnya sebelum update.
2. Backup minimal: folder data\, downloads\, dan config.json bila file itu ada. Cara paling aman adalah backup seluruh folder portable lama.
3. Extract ZIP versi baru ke folder BARU. Jangan menimpa folder lama secara acak saat aplikasi masih berjalan.
4. Salin data\, downloads\, dan config.json dari versi lama ke folder versi baru.
5. Jangan menyalin EXE, _internal\, tools\, VERSION_MANIFEST.json, atau release-info\ dari versi lama ke versi baru.
6. Jalankan versi baru dan pastikan antrean/riwayat/pengaturan terbaca sebelum menghapus backup lama.
7. Key DPAPI terikat pada profil Windows. Jika pindah ke komputer/akun Windows lain, masukkan kembali API key Gemini.

Verifikasi rilis:
- VERSION_MANIFEST.json mencatat Git SHA, versi dependency, dan hash tool yang dibundel.
- release-info\ memuat pin build/runtime yang digunakan.
- File .sha256 di sebelah ZIP rilis digunakan untuk memverifikasi ZIP hasil build.
- THIRD_PARTY_NOTICES.txt memuat sumber lisensi komponen utama.

Gunakan aplikasi hanya untuk media yang Anda berhak atau diizinkan untuk mengunduh.
"@
Set-Content -Path (Join-Path $PackageDir "README_PORTABLE.txt") -Value $PortableReadme -Encoding UTF8

$Required = @(
    (Join-Path $PackageDir "AI Music Downloader.exe"),
    (Join-Path $PackageDir "tools\ffmpeg.exe"),
    (Join-Path $PackageDir "tools\ffprobe.exe"),
    (Join-Path $PackageDir "tools\deno.exe"),
    (Join-Path $PackageDir "README_PORTABLE.txt"),
    (Join-Path $PackageDir "THIRD_PARTY_NOTICES.txt"),
    (Join-Path $PackageDir "VERSION_MANIFEST.json"),
    (Join-Path $PackageDir "release-info\constraints.lock.txt"),
    $PykakasiDb
)
foreach ($Item in $Required) {
    if (-not (Test-Path $Item)) {
        throw "File wajib tidak ditemukan: $Item"
    }
}

Write-Host "[7/9] Creating ZIP and SHA-256 sidecar..."
Compress-Archive -Path $PackageDir -DestinationPath $ZipPath -CompressionLevel Optimal -Force
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path $ZipChecksumPath -Value "$ZipHash  AI-Music-Downloader-Portable.zip" -Encoding ASCII
Write-Host "ZIP_SHA256: $ZipHash"

Write-Host "[8/9] Extracting, relocating, and launching from Unicode/spaces with restricted PATH..."
$SmokeExtract = Join-Path $BuildDir "uji portable 日本語 dengan spasi"
$RelocatedParent = Join-Path $BuildDir "dipindah Δ portable"
$OtherCwd = Join-Path $BuildDir "cwd berbeda"
New-Item -ItemType Directory -Path $SmokeExtract -Force | Out-Null
New-Item -ItemType Directory -Path $RelocatedParent -Force | Out-Null
New-Item -ItemType Directory -Path $OtherCwd -Force | Out-Null
Expand-Archive -Path $ZipPath -DestinationPath $SmokeExtract -Force

$ExtractedPackage = Join-Path $SmokeExtract "AI-Music-Downloader-Portable"
if (-not (Test-Path $ExtractedPackage)) {
    throw "Folder root hasil extract tidak sesuai kontrak portable."
}
$Sentinel = Join-Path $ExtractedPackage "data\relocation-sentinel.txt"
Set-Content -Path $Sentinel -Value "portable-data-survives-relocation" -Encoding ASCII
Move-Item -Path $ExtractedPackage -Destination $RelocatedParent
$RelocatedPackage = Join-Path $RelocatedParent "AI-Music-Downloader-Portable"
$RelocatedSentinel = Join-Path $RelocatedPackage "data\relocation-sentinel.txt"
if (-not (Test-Path $RelocatedSentinel)) {
    throw "Data portable tidak ikut saat seluruh folder dipindahkan."
}

$OriginalPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $RelocatedExe = Join-Path $RelocatedPackage "AI Music Downloader.exe"
    Invoke-ProcessWithTimeout `
        -FilePath $RelocatedExe `
        -ArgumentList @("--self-test") `
        -TimeoutSeconds $SelfTestTimeoutSeconds `
        -WorkingDirectory $OtherCwd
}
finally {
    $env:PATH = $OriginalPath
}
Write-Host "UNICODE_RELOCATED_PORTABLE_SELF_TEST_OK"

Write-Host "[9/9] Final release summary..."
$ZipInfo = Get-Item $ZipPath
Write-Host "PORTABLE_BUILD_OK"
Write-Host ("GIT_SHA: {0}" -f $GitSha)
Write-Host ("ZIP: {0}" -f $ZipInfo.FullName)
Write-Host ("ZIP_CHECKSUM_FILE: {0}" -f $ZipChecksumPath)
Write-Host ("SIZE_MB: {0:N1}" -f ($ZipInfo.Length / 1MB))
Write-Host ("SHA256: {0}" -f $ZipHash)
