"""赛题3 形状分类合成图测试（无相机）。

运行：python test_task3_synthetic.py
"""
from __future__ import annotations

import cv2
import numpy as np

from task3_shapes import detect_shapes

CONFIG = {"task3": {"minimum_object_area_px": 1000, "maximum_object_area_px": 300000}}

passed = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global passed
    assert cond, f"FAIL {name} {extra}"
    passed += 1
    print(f"PASS {name} {extra}")


def classify(draw) -> list[str]:
    canvas = np.full((600, 800, 3), 255, np.uint8)
    draw(canvas)
    objects, _ = detect_shapes(canvas, CONFIG)
    return [o.label for o in objects]


ok("圆/圆柱", classify(lambda c: cv2.circle(c, (400, 300), 100, (0, 0, 0), -1)) == ["circle_or_cylinder"])
ok("正方形→square", classify(lambda c: cv2.rectangle(c, (300, 200), (500, 400), (0, 0, 0), -1)) == ["square"])
ok("长条→rectangle", classify(lambda c: cv2.rectangle(c, (200, 250), (650, 350), (0, 0, 0), -1)) == ["rectangle"])
pentagon = np.array([[400, 150], [540, 260], [480, 430], [320, 430], [260, 260]], np.int32)
ok("五边形→polyhedron", classify(lambda c: cv2.fillPoly(c, [pentagon], (0, 0, 0))) == ["polyhedron"])

# 已知局限（比赛真实场景）：平躺圆柱俯视图是矩形——本分类器会误判。
# 这条测试用来【记录】该局限，而不是掩盖它：真机必须上点云位姿估计。
labels = classify(lambda c: cv2.rectangle(c, (200, 250), (650, 350), (0, 0, 0), -1))
ok("局限已记录：平躺圆柱≠2D圆", labels == ["rectangle"], "2D分类器无法区分，需3D位姿")

print(f"\n全部 {passed} 项通过")
