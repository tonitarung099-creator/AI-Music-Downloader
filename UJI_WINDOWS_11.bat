@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo AI Music Downloader - Uji Windows 11 Fisik
echo ==============================================
echo.
echo Jalankan file ini sebagai user biasa.
echo JANGAN pilih Run as administrator.
echo.
echo Setelah tes otomatis, Anda akan diminta mengonfirmasi:
echo 1. GUI tampil normal.
echo 2. Satu download nyata berhasil.
echo 3. Data tetap terbaca setelah aplikasi ditutup dan dibuka lagi.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0ACCEPTANCE_WINDOWS_11.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if "%EXITCODE%"=="0" (
  echo ==============================================
  echo SEMUA UJI FISIK LULUS - RELEASE_READY=TRUE
  echo ==============================================
  echo Kirim file data\acceptance-windows11.json untuk gate promosi v1.0.0.
) else if "%EXITCODE%"=="2" (
  echo ==============================================
  echo TES OTOMATIS LULUS, GATE MANUAL BELUM LULUS
  echo ==============================================
  echo Lihat data\acceptance-windows11.json lalu ulangi UJI_WINDOWS_11.bat setelah siap.
) else (
  echo ==============================================
  echo UJI WINDOWS 11 GAGAL
  echo ==============================================
  echo Lihat data\acceptance-windows11.json untuk detail.
)
echo.
pause
exit /b %EXITCODE%
