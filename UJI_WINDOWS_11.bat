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
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0ACCEPTANCE_WINDOWS_11.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if "%EXITCODE%"=="0" (
  echo Tes otomatis selesai dengan status LULUS.
) else (
  echo Tes otomatis GAGAL. Lihat data\acceptance-windows11.json.
)
echo.
pause
exit /b %EXITCODE%
