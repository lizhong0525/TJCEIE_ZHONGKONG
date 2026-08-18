# -*- coding: utf-8 -*-
"""比赛机环境一键检查（只依赖标准库，无第三方依赖）。

用法:  <python> env_check.py          （配合 环境检查.bat 双击使用）
退出码: 0 = 全部通过；1 = 存在 [X] 项（必须修复后才能上场）。

检查项与 比赛机环境清单.md §3.4/§5 对应：
  Python 3.11/3.12 | numpy 1.x | opencv contrib(findChessboardCornersSB)
  aiohttp/yaml/requests 可导入 | websockets(可选) | pyorbbecsdk2(相机,真机必须)
  tesseract >=5 + eng.traineddata | 磁盘剩余（wheels 方案要求很低，≥1GB 即可）
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "OK " if ok else "X  "
    print(f"[{tag}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print("=== 比赛机环境一键检查 ===")

    # 1. Python 版本
    v = sys.version_info
    check("Python 版本 3.11/3.12", (v[0], v[1]) in ((3, 11), (3, 12)), f"{v[0]}.{v[1]}.{v[2]}")

    # 2. numpy 1.x
    try:
        import numpy as np
        check("numpy 1.x", np.__version__.startswith("1."), np.__version__)
    except Exception as e:  # noqa: BLE001
        check("numpy 1.x", False, repr(e))

    # 3. opencv contrib（findChessboardCornersSB 只有 contrib 有）
    try:
        import cv2
        check("opencv-contrib (findChessboardCornersSB)", hasattr(cv2, "findChessboardCornersSB"), cv2.__version__)
    except Exception as e:  # noqa: BLE001
        check("opencv-contrib (findChessboardCornersSB)", False, repr(e))

    # 4. 核心服务依赖
    for mod in ("aiohttp", "yaml", "requests"):
        try:
            __import__(mod)
            check(f"{mod} 可导入", True)
        except Exception as e:  # noqa: BLE001
            check(f"{mod} 可导入", False, repr(e))

    # 5. websockets（pyproject 声明、当前代码未 import，缺失仅提示）
    try:
        import websockets  # noqa: F401
        print("[提示] websockets 已装（可选）")
    except Exception:  # noqa: BLE001
        print("[提示] websockets 未装——当前代码未使用，可忽略")

    # 6. pyorbbecsdk2（相机；导入名 pyorbbecsdk；离线自检可跳过，真机必须）
    try:
        import pyorbbecsdk  # noqa: F401
        check("pyorbbecsdk（Gemini335 相机 SDK）", True)
    except Exception as e:  # noqa: BLE001
        check("pyorbbecsdk（Gemini335 相机 SDK）", False, "未安装/不可导入——相机不可用（离线自检可跳过）")

    # 7. tesseract >=5 + eng.traineddata（候选链与 task2_vision.py 一致，除 site.yaml 覆盖）
    cands = [
        os.environ.get("TESSERACT_CMD", ""),
        r"D:\OCR\tesseract.exe",
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    ]
    tess = next((c for c in cands if c and Path(c).exists()), None)
    if tess:
        try:
            out = subprocess.run([tess, "--version"], capture_output=True, text=True, timeout=15)
            first = (out.stdout or out.stderr or "").strip().splitlines()[0] if (out.stdout or out.stderr) else ""
            m = re.search(r"(\d+)\.", first)
            major = int(m.group(1)) if m else 0
            eng = Path(tess).parent / "tessdata" / "eng.traineddata"
            check("tesseract 主版本 >=5", major >= 5, first[:60])
            check("tesseract eng.traineddata", eng.exists(), str(eng))
        except Exception as e:  # noqa: BLE001
            check("tesseract 可执行", False, repr(e))
    else:
        check("找到 tesseract", False, "候选: C:\\Program Files\\Tesseract-OCR\\tesseract.exe / D:\\OCR\\tesseract.exe / PATH")

    # 8. 磁盘剩余（wheels 方案占用很小；提示而非硬失败）
    try:
        free_gb = shutil.disk_usage(os.getcwd()).free / 1e9
        if free_gb < 1.0:
            print(f"[提示] 当前盘剩余 {free_gb:.1f} GB，建议 ≥1GB（wheels 方案占用小，一般足够）")
        else:
            print(f"[OK ] 磁盘剩余 {free_gb:.1f} GB")
    except Exception as e:  # noqa: BLE001
        print(f"[提示] 磁盘空间检查失败: {e!r}")

    print()
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> " + "；".join(FAILS))
        print("按 比赛机环境清单.md 修复后重跑本脚本。")
        return 1
    print("结果：全部通过。可继续 现场安装.bat 的 33 项自检，或直接按 操作指南.md 第 5 节走 11 步。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
