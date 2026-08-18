@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 比赛机环境一键检查 ===
echo.

rem ---- 找 python：优先本目录 env\python.exe（旧 conda 包遗留，一般没有），其次 PATH ----
set "PY="
if exist "%~dp0env\python.exe" set "PY=%~dp0env\python.exe"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [X] 未找到 Python：请先安装 python-3.11.9-amd64.exe（勾 Add to PATH），再双击 现场安装.bat
  pause
  exit /b 1
)
echo 使用 Python: %PY%
echo.

"%PY%" "%~dp0env_check.py"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo 环境检查通过。下一步：现场安装.bat 的 33 项自检（如未跑）→ 操作指南.md 第 5 节 11 步。
) else (
  echo 环境有缺口：按上方 [X] 项和 比赛机环境清单.md 修复后重跑。
)
pause
exit /b %RC%
