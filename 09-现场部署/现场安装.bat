@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 现场部署（比赛机，无外网）===

rem ---- 0. 预检系统 Python（3.11.9 官方安装器，须勾 Add to PATH）----
where python >nul 2>nul
if errorlevel 1 (
  echo [失败] 找不到 python（未安装或 PATH 未生效）。请先装 python-3.11.9-amd64.exe 并勾选 "Add python.exe to PATH"，重开命令行再跑。
  pause
  exit /b 1
)
python -c "import sys; assert sys.version_info[:2] in ((3,11),(3,12)), sys.version; print('Python', sys.version.split()[0])" >nul 2>nul
if errorlevel 1 (
  echo [失败] 系统 python 版本不是 3.11/3.12。请用 python-3.11.9-amd64.exe（统一 3.11）。
  pause
  exit /b 1
)
echo [0/4] Python 版本 OK

rem ---- 1. wheels 离线安装（唯一方案；精确版本，缺包时降级 >= 下限）----
if not exist "wheels" (
  echo [失败] 未找到 wheels\ 目录。请用有网机跑 下载wheels.bat 生成后放入本目录。
  pause
  exit /b 1
)
echo [1/4] 离线安装 6 个 pip 依赖（--no-index --find-links=wheels）...
set "PKGS_EXACT=aiohttp==3.11.11 pyyaml==6.0.2 numpy==1.26.4 opencv-contrib-python==4.10.0.84 requests==2.32.3 pyorbbecsdk2==2.0.15"
set "PKGS_LOOSE=aiohttp>=3.9 pyyaml>=6.0 "numpy>=1.26,<2" opencv-contrib-python>=4.8 requests>=2.31 pyorbbecsdk2>=2.0.15"
python -m pip install --no-index --find-links=wheels %PKGS_EXACT%
if errorlevel 1 (
  echo [重试] 精确版本未全部命中（wheel 缺失/版本不符），改用 >= 下限重试...
  python -m pip install --no-index --find-links=wheels %PKGS_LOOSE%
  if errorlevel 1 (
    echo [失败] wheels 离线安装失败：检查 wheels\ 是否完整、Python 是否 3.11。
    pause
    exit /b 1
  )
)
set "PY=python"

:smoke
echo.
echo [冒烟] import + ssl + 版本红线（ssl 崩 = 环境混装；缺 contrib / numpy 2.x / Python 非 3.11-3.12 全在这里拦）
"%PY%" -c "import sys, ssl, cv2, numpy, aiohttp, requests, yaml; ssl.create_default_context(); assert hasattr(cv2, 'findChessboardCornersSB'), 'opencv 必须 contrib 版（手眼标定要 findChessboardCornersSB）'; assert numpy.__version__.split('.')[0] == '1', 'numpy 必须 1.x'; assert sys.version_info[:2] in ((3, 11), (3, 12)), 'Python 必须 3.11/3.12'; print('imports OK')"
if errorlevel 1 (
  echo [失败] import/版本断言报错：官方 Python 3.11.9 + wheels 一般不会 ssl 混装；
  echo        若真出现 ASN1 错误，多半是本机 PATH 里混入了 conda 的 python——重装 Python 并清 PATH。
  pause
  exit /b 1
)

echo.
echo [冒烟] 相机 SDK（pyorbbecsdk2——装没装对只有 import 了才知道）
"%PY%" -c "import pyorbbecsdk; print('pyorbbecsdk OK')"
if errorlevel 1 (
  echo [失败] pyorbbecsdk 导入失败：pyorbbecsdk2 与 Python 版本/系统严格匹配，三赛题全靠相机
  pause
  exit /b 1
)

echo.
echo [检查] Tesseract eng 语言数据 + 主版本（OCR 命根子；4.x 的 psm 8 行为不同可能读错数字）
set "TESS="
if exist "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" set "TESS=C:\Program Files\Tesseract-OCR\tesseract.exe"
if exist "D:\OCR\tessdata\eng.traineddata" set "TESS=D:\OCR\tesseract.exe"
if not defined TESS (
  echo [警告] 没找到带 eng.traineddata 的 tesseract！task2 数字 OCR 会全灭。
  echo        请安装 Tesseract 并勾选 English 语言数据。
  goto selftest
)
echo tesseract eng 数据 OK: %TESS%
"%TESS%" --version 2>&1 | findstr /r /c:"tesseract [5-9]" >nul
if errorlevel 1 (
  echo [警告] tesseract 主版本疑似 ^<5，--psm 8 行为不同，可能读错数字——建议换装 5.x
) else (
  echo tesseract 版本 OK
)

:selftest
echo.
echo [自检] 跑端到端自检（不需要硬件，33 项应全 PASS）
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
