@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 下载离线 wheel 包（在有网机器上跑）===
echo 版本锚点（与 比赛机环境清单.md §3.4 一致，比赛机无外网，必须预先下全）：
echo   aiohttp==3.11.11  pyyaml==6.0.2  numpy==1.26.4
echo   opencv-contrib-python==4.10.0.84  requests==2.32.3  pyorbbecsdk2==2.0.15
echo.
echo 注意：--python-version 必须与比赛机 Python 完全一致（当前统一 3.11，勿改 3.12 除非比赛机也装 3.12）

rem 比赛机 Python 版本（赛前确认后改这里，只允许 3.11 或 3.12）
set "PY_VER=3.11"

rem 精确版本优先；某版本拉不到时（pip 报错）去掉 == 用 >= 下限自动取最新：
rem   aiohttp>=3.9  pyyaml>=6.0  numpy>=1.26,<2  opencv-contrib-python>=4.8  requests>=2.31  pyorbbecsdk2>=2.0.15
set "PKGS=aiohttp==3.11.11 pyyaml==6.0.2 numpy==1.26.4 opencv-contrib-python==4.10.0.84 requests==2.32.3 pyorbbecsdk2==2.0.15"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m pip download %PKGS% -d wheels --platform win_amd64 --python-version %PY_VER% --only-binary=:all:
) else (
  python -m pip download %PKGS% -d wheels --platform win_amd64 --python-version %PY_VER% --only-binary=:all:
)
if errorlevel 1 (
  echo.
  echo [失败] 精确版本下载失败：检查网络 / 包名 / 该版本是否有 win_amd64 cp%PY_VER% wheel。
  echo        按上面备注改用 >= 下限重跑，或对照 比赛机环境清单.md 手动补齐。
  pause
  exit /b 1
)

echo.
echo 完成。U 盘还要带：python-3.11.9-amd64.exe（勾 Add to PATH）+ Tesseract 5.x 安装包（勾 English）。
pause
