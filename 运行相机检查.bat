@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 tools\check_camera.py
) else (
  python tools\check_camera.py
)
echo.
pause
