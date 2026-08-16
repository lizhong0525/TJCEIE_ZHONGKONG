# 09-现场部署（离线安装包）

赛方工控机**无外网**，所有依赖在家打包好带 U 盘去。不做 Docker 全量镜像——依赖很轻
（aiohttp/pyyaml/numpy/opencv/requests + pyorbbecsdk2），镜像化收益不大。

## U 盘清单

- [ ] `wheels/`（用 `下载wheels.bat` 在家生成，~200MB）
- [ ] Tesseract 安装包（`tesseract-ocr-w64-setup-*.exe`，**必须带 eng 语言数据**——
      本机 D:\OCR 只有 chi_sim 曾导致 OCR 静默全灭，代码只认带 eng.traineddata 的 exe）
- [ ] `work/` 全目录（或 git 仓库最新 clone）
- [ ] 奥比中光 SDK 的相机驱动/运行时（如 pyorbbecsdk2 wheel 装不上时的官方安装包）

## 在家（有网机器）

双击 `下载wheels.bat`，或手动：

```powershell
pip download aiohttp pyyaml numpy requests opencv-contrib-python pyorbbecsdk2 ^
  -d wheels --platform win_amd64 --python-version 3.11 --only-binary=:all:
```

⚠️ `--python-version` 必须和**比赛机**的 Python 版本一致（我方代码要求 3.11/3.12）。
比赛机若是 3.10，先在家确认代码在 3.10 能跑（`pyproject.toml` 写的是 >=3.11，要降得先测）。

## 现场（比赛机，无外网）

1. 装 Python 3.11+（勾选 Add to PATH），装 Tesseract（记下安装目录）。
2. 双击 `现场安装.bat`：离线装 wheels + 校验 tesseract 的 eng.traineddata + 冒烟 `import aiohttp`。
3. `cd 01-算法服务 && python -m tools.service_selftest` 应 28 项全 PASS（不需要任何硬件）。
4. 插相机/连臂手后按 `../现场调试清单.md` 走 11 步。

## 已知坑（都踩过）

- `import aiohttp` 崩 = conda ssl 混装（Anaconda 的 openssl 与 Python 不配套）——
  比赛机尽量用 python.org 官方安装包，别用 conda；或先跑 `python -c "import aiohttp"` 验证。
- tesseract 装了但 OCR 全空 = 装的时候没勾 eng 语言数据，或 tessdata 目录缺 eng.traineddata。
- `pyorbbecsdk2` 装不上 = Python 版本不在其支持列表，换官方运行时或降/升 Python。
