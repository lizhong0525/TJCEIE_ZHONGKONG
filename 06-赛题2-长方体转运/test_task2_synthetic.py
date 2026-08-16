"""赛题2 数字块识别合成图测试（无相机，用本机 Tesseract OCR）。

运行：python test_task2_synthetic.py
"""
from __future__ import annotations

import cv2
import numpy as np

from task2_blocks import detect_number_blocks

CONFIG = {
    "task2": {
        "minimum_block_area_px": 800,
        "maximum_block_area_px": 200000,
        "tesseract_command": r"C:/Program Files/Tesseract-OCR/tesseract.exe",
        "ocr_language": "eng",
    }
}

passed = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global passed
    assert cond, f"FAIL {name} {extra}"
    passed += 1
    print(f"PASS {name} {extra}")


# 单数字 1-4 逐一识别
for digit in "1234":
    canvas = np.full((400, 400, 3), 255, np.uint8)
    cv2.putText(canvas, digit, (120, 300), cv2.FONT_HERSHEY_SIMPLEX, 8, (0, 0, 0), 20)
    blocks, _ = detect_number_blocks(canvas, CONFIG)
    found = [b.digit for b in blocks if b.digit is not None]
    ok(f"数字 {digit}", found == [int(digit)], f"检出={found}")

# 四块同图：检测出 4 个候选且数字各不相同
canvas = np.full((600, 1200, 3), 255, np.uint8)
for i, digit in enumerate("3142"):
    cv2.putText(canvas, digit, (80 + i * 300, 420), cv2.FONT_HERSHEY_SIMPLEX, 8, (0, 0, 0), 20)
blocks, _ = detect_number_blocks(canvas, CONFIG)
digits = sorted(b.digit for b in blocks if b.digit is not None)
ok("四块同图检出", digits == [1, 2, 3, 4], f"检出={digits}")

print(f"\n全部 {passed} 项通过")
