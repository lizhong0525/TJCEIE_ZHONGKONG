"""赛题 3 视觉分类 —— 多面体形状（圆形/方形/异形）。

* 轮廓提取 → ``cv2.minAreaRect`` 取最小外接矩形。
* 圆度 = 4πA/P²；越接近 1 越像圆。
* 长宽比 ≈ 1 → 方形候选；圆度高 → 圆形；其余异形。
* 返回 ``[(block_id, shape_name, pick_pose)]``。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

LOG = logging.getLogger(__name__)


@dataclass
class _Shape:
    block_id: str
    shape: str
    pick: Any


def classify_shapes(
    color_bgr: Any,
    depth_mm: Any | None,
    cfg: Any,
) -> list[_Shape]:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    if color_bgr is None:
        return []

    gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(bw, 60, 180)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = color_bgr.shape[:2]
    out: list[_Shape] = []
    staging = cfg.shapes.staging_area
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < (h * w) * 0.005:
            continue
        perim = cv2.arcLength(cnt, True)
        if perim <= 0:
            continue
        circ = 4 * 3.14159 * area / (perim * perim)
        rect = cv2.minAreaRect(cnt)
        bw_, bh_ = rect[1]
        if min(bw_, bh_) < 25:
            continue
        ratio = max(bw_, bh_) / max(1e-3, min(bw_, bh_))

        if circ > 0.80:
            shape = "round"
        elif ratio < 1.25 and 0.55 < circ < 0.80:
            shape = "square"
        else:
            shape = "irregular"

        cx, cy = int(rect[0][0]), int(rect[0][1])
        bx, by, bz = float(staging.x), float(staging.y), float(staging.z)
        if depth_mm is not None:
            if 0 <= cy < depth_mm.shape[0] and 0 <= cx < depth_mm.shape[1]:
                d = int(depth_mm[cy, cx])
                if 100 < d < 5000:
                    try:
                        from ..vision import Vision  # type: ignore
                        v = Vision(
                            intrinsics=(cfg.camera.fx, cfg.camera.fy, cfg.camera.cx, cfg.camera.cy),
                            distortion=(cfg.distortion.k1, cfg.distortion.k2, cfg.distortion.p1, cfg.distortion.p2),
                            hand_eye=cfg.hand_eye.matrix,
                        )
                        bx, by, bz = v.pixel_to_base(cx, cy, d / 1000.0)
                    except Exception as e:  # noqa: BLE001
                        LOG.debug("手眼变换失败：%s", e)
        from ..planner import Pose  # 避免循环
        out.append(_Shape(block_id=f"shape_{i}", shape=shape, pick=Pose(bx, by, bz)))
        if i >= 16:
            break
    return out
