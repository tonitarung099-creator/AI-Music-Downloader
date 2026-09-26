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

Write-Host "[1/5] Building one-folder EXE with PyInstaller..."
& python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "AI Music Downloader" `
    --collect-all spotdl `
    --collect-all yt_dlp `
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
if (-not (Test-Path (Join-Path $BuiltApp "AI Music Downloader.exe"))) {
    throw "Hasil build EXE tidak ditemukan."
}

Write-Host "[2/5] Preparing portable folder..."
New-Item -ItemType Directory -Path $PackageDir | Out-Null
Copy-Item (Join-Path $BuiltApp "*") $PackageDir -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $PackageDir "tools") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "downloads") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "data") | Out-Null
Copy-Item (Join-Path $Root "config.example.json") (Join-Path $PackageDir "config.example.json") -Force

Write-Host "[3/5] Downloading portable FFmpeg essentials..."
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

$PortableReadme = @"
AI MUSIC DOWNLOADER - PORTABLE WINDOWS
======================================

Cara menjalankan:
1. Extract seluruh ZIP ke satu folder.
2. Jalankan: AI Music Downloader.exe
3. Tidak perlu installer dan tidak perlu Python terpasang.
4. Jangan memindahkan EXE sendirian; folder _internal dan tools harus tetap bersamanya.

Folder penting:
- downloads\  : hasil download default
- data\       : data lokal aplikasi
- tools\      : FFmpeg portable
- config.json : dibuat otomatis saat pengaturan disimpan

Mode audio:
- Original / Best Audio: menyimpan stream audio terbaik tanpa transcoding tambahan.
- M4A: memprioritaskan source M4A bila tersedia.
- MP3: membutuhkan FFmpeg yang sudah dibundel di tools\.

Spotify:
Spotify hanya digunakan untuk membaca metadata track/album/playlist. Audio Spotify/DRM tidak diakses.

Gunakan aplikasi hanya untuk media yang Anda berhak atau diizinkan untuk mengunduh.

FFmpeg:
Binary FFmpeg dalam folder tools berasal dari build essentials Gyan.dev.
FFmpeg adalah proyek pihak ketiga dan memiliki lisensi tersendiri: https://ffmpeg.org/legal.html
"@
Set-Content -Path (Join-Path $PackageDir "README_PORTABLE.txt") -Value $PortableReadme -Encoding UTF8

Write-Host "[4/5] Verifying package..."
$Required = @(
    (Join-Path $PackageDir "AI Music Downloader.exe"),
    (Join-Path $PackageDir "tools\ffmpeg.exe"),
    (Join-Path $PackageDir "README_PORTABLE.txt")
)
foreach ($Item in $Required) {
    if (-not (Test-Path $Item)) {
        throw "File wajib tidak ditemukan: $Item"
    }
}

Write-Host "[5/5] Creating ZIP..."
Compress-Archive -Path $PackageDir -DestinationPath $ZipPath -CompressionLevel Optimal -Force

$ZipInfo = Get-Item $ZipPath
Write-Host "PORTABLE_BUILD_OK"
Write-Host ("ZIP: {0}" -f $ZipInfo.FullName)
Write-Host ("SIZE_MB: {0:N1}" -f ($ZipInfo.Length / 1MB))
