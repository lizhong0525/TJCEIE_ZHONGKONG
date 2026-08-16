@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 下载离线 wheel 包（在有网机器上跑）===
echo 注意：--python-version 必须与比赛机一致（代码要求 3.11/3.12）
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m pip download aiohttp pyyaml numpy requests opencv-contrib-python pyorbbecsdk2 -d wheels --platform win_amd64 --python-version 3.11 --only-binary=:all:
) else (
  python -m pip download aiohttp pyyaml numpy requests opencv-contrib-python pyorbbecsdk2 -d wheels --platform win_amd64 --python-version 3.11 --only-binary=:all:
)
echo.
echo 完成。wheels\ 目录拷进 U 盘，别忘了 Tesseract 安装包（要带 eng 语言数据）。
pause
