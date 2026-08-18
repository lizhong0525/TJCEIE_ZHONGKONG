@echo off
chcp 65001 >nul
echo ============================================================
echo  [已废弃] conda-pack 方案不再使用（2026-08-18 起）
echo ============================================================
echo.
echo 比赛环境已改为「安装列表」方案，无需 conda、无需打包 tar.gz：
echo   - 系统：python-3.11.9-amd64.exe（官方安装器，勾 Add to PATH）
echo          + Tesseract 5.x（UB-Mannheim，勾 English）
echo   - pip：6 个包精确版本，离线 wheels（见 比赛机环境清单.md §3.4）
echo.
echo 请改用：
echo   1. 有网机：双击 下载wheels.bat      （生成 wheels）
echo   2. 比赛机：装 Python + Tesseract，双击 现场安装.bat
echo            （自动离线装 wheels + 冒烟 + 33 项自检）
echo   3. 复核：双击 环境检查.bat
echo.
echo 本文件保留仅为说明历史；不再执行任何打包动作。
pause
exit /b 0
