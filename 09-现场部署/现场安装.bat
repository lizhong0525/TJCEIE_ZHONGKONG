@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 现场离线安装（比赛机，无外网）===
echo [1/4] 安装 Python 依赖（离线，从 wheels\ 目录取）
python -m pip install --no-index --find-links=wheels aiohttp pyyaml numpy requests opencv-contrib-python pyorbbecsdk2
if errorlevel 1 (
  echo [失败] pip 离线安装失败，检查 wheels\ 是否完整、Python 版本是否与下载时指定的一致
  pause
  exit /b 1
)
echo.
echo [2/4] 冒烟验证 import aiohttp（conda ssl 混装机会在这一步崩）
python -c "import aiohttp, cv2, numpy, requests, yaml; print('imports OK')"
if errorlevel 1 (
  echo [失败] import 报错——若是 ssl/ASN1 错误，说明是 conda 混装，请换 python.org 官方 Python
  pause
  exit /b 1
)
echo.
echo [3/4] 检查 Tesseract eng 语言数据（OCR 命根子）
set TESS1=C:\Program Files\Tesseract-OCR\tesseract.exe
set TESS2=D:\OCR\tesseract.exe
if exist "%TESS1%\..\tessdata\eng.traineddata" goto tess_ok
if exist "%TESS2%\..\tessdata\eng.traineddata" goto tess_ok
echo [警告] 没找到带 eng.traineddata 的 tesseract！task2 数字 OCR 会全灭。
echo        请安装 Tesseract 并勾选 English 语言数据。
goto tess_done
:tess_ok
echo tesseract eng 数据 OK
:tess_done
echo.
echo [4/4] 跑端到端自检（不需要硬件，28 项应全 PASS）
cd /d "%~dp0..\01-算法服务"
python -m tools.service_selftest
echo.
echo 全部完成。接下来按 ..\现场调试清单.md 走 11 步。
pause
