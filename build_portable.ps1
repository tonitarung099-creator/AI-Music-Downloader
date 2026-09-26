$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"
$ReleaseDir = Join-Path $Root "release"
$PackageDir = Join-Path $ReleaseDir "AI-Music-Downloader-Portable"
$ZipPath = Join-Path $ReleaseDir "AI-Music-Downloader-Portable.zip"

Write-Host "== AI Music Downloader: portable Windows build =="

foreach ($Path in @($BuildDir, $DistDir, $ReleaseDir)) {
    if (Test-Path $Path) {
        Remove-Item $Path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

Write-Host "[1/7] Building one-folder EXE with PyInstaller..."
& python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "AI Music Downloader" `
    --collect-all spotdl `
    --collect-all yt_dlp `
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

Write-Host "[2/7] Preparing portable folder..."
New-Item -ItemType Directory -Path $PackageDir | Out-Null
Copy-Item (Join-Path $BuiltApp "*") $PackageDir -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $PackageDir "tools") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "downloads") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "data") | Out-Null
Copy-Item (Join-Path $Root "config.example.json") (Join-Path $PackageDir "config.example.json") -Force

$PykakasiDb = Join-Path $PackageDir "_internal\pykakasi\data\kanwadict4.db"
if (-not (Test-Path $PykakasiDb)) {
    throw "Data runtime pykakasi tidak ikut terbundle: $PykakasiDb"
}

Write-Host "[3/7] Downloading portable FFmpeg essentials..."
$FfmpegZip = Join-Path $BuildDir "ffmpeg.zip"
$FfmpegExtract = Join-Path $BuildDir "ffmpeg"
$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
Invoke-WebRequest -Uri $FfmpegUrl -OutFile $FfmpegZip -UseBasicParsing
Expand-Archive -Path $FfmpegZip -DestinationPath $FfmpegExtract -Force

$FfmpegExe = Get-ChildItem $FfmpegExtract -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
$FfprobeExe = Get-ChildItem $FfmpegExtract -Filter "ffprobe.exe" -Recurse | Select-Object -First 1
if (-not $FfmpegExe) {
    throw "ffmpeg.exe tidak ditemukan di paket FFmpeg."
}
Copy-Item $FfmpegExe.FullName (Join-Path $PackageDir "tools\ffmpeg.exe") -Force
if ($FfprobeExe) {
    Copy-Item $FfprobeExe.FullName (Join-Path $PackageDir "tools\ffprobe.exe") -Force
}

Write-Host "[4/7] Downloading and verifying portable Deno runtime..."
$DenoZip = Join-Path $BuildDir "deno.zip"
$DenoSum = Join-Path $BuildDir "deno.zip.sha256sum"
$DenoExtract = Join-Path $BuildDir "deno"
$DenoUrl = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
$DenoSumUrl = "$DenoUrl.sha256sum"
Invoke-WebRequest -Uri $DenoUrl -OutFile $DenoZip -UseBasicParsing
Invoke-WebRequest -Uri $DenoSumUrl -OutFile $DenoSum -UseBasicParsing

$ExpectedDenoHash = ((Get-Content $DenoSum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$ActualDenoHash = (Get-FileHash -Path $DenoZip -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $ExpectedDenoHash -or $ExpectedDenoHash -ne $ActualDenoHash) {
    throw "Checksum Deno tidak cocok. Expected=$ExpectedDenoHash Actual=$ActualDenoHash"
}

Expand-Archive -Path $DenoZip -DestinationPath $DenoExtract -Force
$DenoExe = Get-ChildItem $DenoExtract -Filter "deno.exe" -Recurse | Select-Object -First 1
if (-not $DenoExe) {
    throw "deno.exe tidak ditemukan di paket Deno."
}
$PortableDeno = Join-Path $PackageDir "tools\deno.exe"
Copy-Item $DenoExe.FullName $PortableDeno -Force
& $PortableDeno --version | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "deno.exe gagal dijalankan dengan exit code $LASTEXITCODE"
}

Write-Host "[5/7] Running frozen EXE self-test..."
$PortableExe = Join-Path $PackageDir "AI Music Downloader.exe"
$SelfTest = Start-Process -FilePath $PortableExe -ArgumentList "--self-test" -Wait -PassThru
if ($SelfTest.ExitCode -ne 0) {
    throw "Self-test EXE portable gagal dengan exit code $($SelfTest.ExitCode)"
}
Write-Host "FROZEN_EXE_SELF_TEST_OK"

Write-Host "[6/7] Writing README and verifying package..."
$PortableReadme = @"
AI MUSIC DOWNLOADER - PORTABLE WINDOWS
======================================

Cara menjalankan:
1. Extract seluruh ZIP ke satu folder.
2. Jalankan: AI Music Downloader.exe
3. Tidak perlu installer, Python, FFmpeg, atau Deno terpasang di Windows.
4. Jangan memindahkan EXE sendirian; folder _internal dan tools harus tetap bersamanya.

Folder penting:
- downloads\  : hasil download default
- data\       : data lokal aplikasi
- tools\      : FFmpeg, ffprobe, dan Deno portable
- config.json : dibuat otomatis saat pengaturan disimpan

Mode audio:
- Original / Best Audio: menyimpan stream audio terbaik tanpa transcoding tambahan.
- M4A: memprioritaskan source M4A bila tersedia.
- MP3: menggunakan FFmpeg portable di tools\.

YouTube:
Deno portable dibundel agar yt-dlp dapat menangani JavaScript challenge YouTube tanpa instalasi tambahan.

Spotify:
Spotify hanya digunakan untuk membaca metadata track/album/playlist. Audio Spotify/DRM tidak diakses.

Gunakan aplikasi hanya untuk media yang Anda berhak atau diizinkan untuk mengunduh.

Komponen pihak ketiga:
- FFmpeg: https://ffmpeg.org/legal.html
- Deno runtime: https://github.com/denoland/deno (MIT License)
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- spotDL: https://github.com/spotDL/spotify-downloader
"@
Set-Content -Path (Join-Path $PackageDir "README_PORTABLE.txt") -Value $PortableReadme -Encoding UTF8

$Required = @(
    (Join-Path $PackageDir "AI Music Downloader.exe"),
    (Join-Path $PackageDir "tools\ffmpeg.exe"),
    (Join-Path $PackageDir "tools\deno.exe"),
    (Join-Path $PackageDir "README_PORTABLE.txt"),
    $PykakasiDb
)
foreach ($Item in $Required) {
    if (-not (Test-Path $Item)) {
        throw "File wajib tidak ditemukan: $Item"
    }
}

Write-Host "[7/7] Creating ZIP..."
Compress-Archive -Path $PackageDir -DestinationPath $ZipPath -CompressionLevel Optimal -Force

$ZipInfo = Get-Item $ZipPath
Write-Host "PORTABLE_BUILD_OK"
Write-Host ("ZIP: {0}" -f $ZipInfo.FullName)
Write-Host ("SIZE_MB: {0:N1}" -f ($ZipInfo.Length / 1MB))
