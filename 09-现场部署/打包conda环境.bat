@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 在家打包 conda 完整环境（比赛机离线解压即用）===
echo 要求：本机已装 conda（Anaconda/Miniconda 均可），有网络。
echo 产物：zkc_env.tar.gz（约 600MB-1GB，含 python+全部依赖，自包含无混装）

where conda >nul 2>nul
if errorlevel 1 (
  echo [失败] 找不到 conda，请先安装 Anaconda 或 Miniconda
  pause
  exit /b 1
)

echo.
echo [1/5] 创建环境 zkc（python 3.11，与代码 requires-python 一致）
conda create -y -n zkc python=3.11
if errorlevel 1 (
  echo [失败] 环境创建失败
  pause
  exit /b 1
)

echo.
echo [2/5] 安装 conda-pack（打包工具，装进 zkc 环境随包带走）
conda install -y -n zkc -c conda-forge conda-pack
if errorlevel 1 (
  echo [失败] conda-pack 安装失败
  pause
  exit /b 1
)

echo.
echo [3/5] pip 安装项目依赖（全部装进 zkc 环境，打包时一起带走）
conda run -n zkc python -m pip install aiohttp pyyaml numpy requests opencv-contrib-python pyorbbecsdk2
if errorlevel 1 (
  echo [失败] pip 安装失败
  pause
  exit /b 1
)

echo.
echo [4/5] 打包前冒烟验证（含 ssl——混装环境会在这里崩）
conda run -n zkc python -c "import aiohttp, cv2, numpy, requests, yaml, ssl; ssl.create_default_context(); print('imports OK')"
if errorlevel 1 (
  echo [失败] 冒烟不过。若是 ssl/ASN1 错误 = 本机 conda 混装（python 与 openssl 不同渠道），
  echo        先执行 conda update --all 或 conda install -n zkc openssl --channel defaults 对齐后再试
  pause
  exit /b 1
)

echo.
echo [5/5] 打包（环境未激活时打包，避免缓存文件混入）
conda run -n zkc conda-pack -n zkc -o zkc_env.tar.gz
if errorlevel 1 (
  echo [失败] 打包失败
  pause
  exit /b 1
)

echo.
echo ============================================
echo 完成：%~dp0zkc_env.tar.gz
echo 拷进 U 盘（和 Tesseract 安装包、work 目录一起），
echo 比赛机跑 现场安装.bat 会自动解压并使用（无需装 conda）。
echo ============================================
pause
