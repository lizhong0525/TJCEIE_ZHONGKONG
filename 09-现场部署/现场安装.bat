@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 现场部署（比赛机，无外网）===

rem ---- 方案 A（推荐）：conda-pack 完整环境，自包含无混装 ----
if not exist "env\python.exe" (
  if exist "zkc_env.tar.gz" (
    echo [A1/4] 解压 conda 环境包 zkc_env.tar.gz（需 2-3GB 磁盘空间，约 1-2 分钟）...
    mkdir env >nul 2>nul
    tar -xzf zkc_env.tar.gz -C env
    if errorlevel 1 (
      echo [失败] 解压失败：磁盘空间不足，或 Windows tar 不可用（Win10 1803+ 自带 tar）
      pause
      exit /b 1
    )
    echo [A2/4] 修正环境路径前缀（conda-unpack）...
    "env\Scripts\conda-unpack.exe"
    if errorlevel 1 (
      echo [失败] conda-unpack 失败，环境包可能损坏
      pause
      exit /b 1
    )
  )
)

if exist "env\python.exe" (
  set "PY=%~dp0env\python.exe"
  echo [A3/4] 使用 conda 完整环境：%PY%
  goto smoke
)

rem ---- 方案 B（备选）：wheels + 系统 Python ----
echo [B1/3] 未找到 conda 环境包（env\ 或 zkc_env.tar.gz），改用 wheels + 系统 Python
python -m pip install --no-index --find-links=wheels aiohttp pyyaml numpy requests opencv-contrib-python pyorbbecsdk2
if errorlevel 1 (
  echo [失败] wheels 离线安装失败：检查 wheels\ 是否完整、Python 版本是否与下载时指定的一致
  pause
  exit /b 1
)
set "PY=python"

:smoke
echo.
echo [冒烟] 验证 import + ssl（ssl 崩 = 环境混装；conda 完整包不应出现）
"%PY%" -c "import aiohttp, cv2, numpy, requests, yaml, ssl; ssl.create_default_context(); print('imports OK')"
if errorlevel 1 (
  echo [失败] import 报错。若是 ssl/ASN1 错误：
  echo         - 方案A 环境：理论上不会发生，请重新打包（打包前先 conda update --all）
  echo         - 方案B 环境：conda 混装，改用方案A 的 conda 完整包
  pause
  exit /b 1
)

echo.
echo [检查] Tesseract eng 语言数据（OCR 命根子）
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
echo [自检] 跑端到端自检（不需要硬件，28 项应全 PASS）
cd /d "%~dp0..\01-算法服务"
"%PY%" -m tools.service_selftest
if errorlevel 1 (
  echo [失败] 自检未全过，先解决上面红叉再上场
  pause
  exit /b 1
)

echo.
echo 全部完成。接下来按 ..\操作指南.md 第 5 节走 11 步。
pause
