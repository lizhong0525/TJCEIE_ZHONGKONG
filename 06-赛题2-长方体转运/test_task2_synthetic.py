"""赛题2 数字块识别合成图测试（无相机，用本机 Tesseract OCR）。

渲染风格与 01-算法服务 selftest 的 digits_image() 一致：黑底 canvas + 白色块 +
黑数字（scale 1.8 / thickness 5）。历史教训：scale 8 / thickness 20 的 Hershey
大字不同版本 tesseract 读法不一（2 读空、3 读成 5），测试结论不可信。

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


def draw_block(canvas: np.ndarray, cx: int, cy: int, digit: str) -> None:
    """白色 110x80 块 + 居中黑数字（01 selftest 同款参数）。"""

    cv2.rectangle(canvas, (cx - 55, cy - 40), (cx + 55, cy + 40), (255, 255, 255), -1)
    cv2.putText(canvas, digit, (cx - 18, cy + 22), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 5)


# 单数字 1-4 逐一识别
for digit in "1234":
    canvas = np.zeros((400, 400, 3), np.uint8)
    draw_block(canvas, 200, 200, digit)
    blocks, _ = detect_number_blocks(canvas, CONFIG)
    found = [b.digit for b in blocks if b.digit is not None]
    ok(f"数字 {digit}", found == [int(digit)], f"检出={found}")

# 四块同图：检测出 4 个候选且数字各不相同
canvas = np.zeros((600, 1200, 3), np.uint8)
for i, digit in enumerate("3142"):
    draw_block(canvas, 150 + i * 300, 300, digit)
blocks, _ = detect_number_blocks(canvas, CONFIG)
digits = sorted(b.digit for b in blocks if b.digit is not None)
ok("四块同图检出", digits == [1, 2, 3, 4], f"检出={digits}")

print(f"\n全部 {passed} 项通过")
