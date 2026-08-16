"""赛题1 亮灯识别合成图测试（无相机）。

运行：python test_task1_synthetic.py
"""
from __future__ import annotations

import numpy as np

from task1_lamp import detect_lit_lamp

CONFIG = {
    "task1": {
        "lamp_rois_normalized": {
            "button_1": [0.02, 0.05, 0.30, 0.40],
            "button_2": [0.35, 0.05, 0.63, 0.40],
            "toggle": [0.68, 0.05, 0.96, 0.40],
        },
        "minimum_brightness_score": 120.0,
        "minimum_winner_margin": 12.0,
    }
}

passed = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global passed
    assert cond, f"FAIL {name} {extra}"
    passed += 1
    print(f"PASS {name} {extra}")


# 三个 ROI 各亮一次，每次都必须选对
for name, (x0, x1) in {"button_1": (13, 192), "button_2": (224, 403), "toggle": (435, 614)}.items():
    img = np.zeros((480, 640, 3), np.uint8)
    img[24:192, x0:x1] = (0, 0, 255)
    det, _ = detect_lit_lamp(img, CONFIG)
    ok(f"选中 {name}", det.target == name, f"margin={det.confidence_margin:.1f}")

# 全暗必须拒绝（不能瞎猜坐标去动机械臂）
try:
    detect_lit_lamp(np.zeros((480, 640, 3), np.uint8), CONFIG)
    raise SystemExit("FAIL: 全暗未拒绝")
except RuntimeError as e:
    ok("全暗拒绝", "不像亮灯" in str(e))

# 两个一样亮必须拒绝
img = np.zeros((480, 640, 3), np.uint8)
img[24:192, 224:403] = (0, 0, 255)
img[24:192, 435:614] = (0, 0, 255)
try:
    detect_lit_lamp(img, CONFIG)
    raise SystemExit("FAIL: 并列未拒绝")
except RuntimeError as e:
    ok("并列拒绝", "不唯一" in str(e))

# ROI 未标定必须拒绝（安全设计）
try:
    detect_lit_lamp(np.zeros((480, 640, 3), np.uint8), {"task1": {"lamp_rois_normalized": {}}})
    raise SystemExit("FAIL: 未标定未拒绝")
except RuntimeError as e:
    ok("未标定拒绝", "标定" in str(e))

print(f"\n全部 {passed} 项通过")
