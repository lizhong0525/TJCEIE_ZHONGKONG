"""赛题 3 视觉分类 —— 多面体形状（圆形/方形/异形）。

* 轮廓提取 → ``cv2.minAreaRect`` 取最小外接矩形。
* 圆度 = 4πA/P²；越接近 1 越像圆。
* 长宽比 ≈ 1 → 方形候选；圆度高 → 圆形；其余异形。
* 坐标解算：深度有效走手眼变换；无深度图回退 ``shapes.staging_area``
  （必须已标定，否则抛 ``PickError``；仅自检场景合理）。
* 返回 ``[(block_id, shape_name, pick_pose)]``。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from ..planner import Pose
from ._coords import center_depth_m, pixel_to_base_pose, staging_pose

from .pose_estimator import estimate_6d_pose

LOG = logging.getLogger(__name__)


@dataclass
class _Shape:
    block_id: str
    shape: str
    pick: Pose


def classify_shapes(
    color_bgr: Any,
    depth_mm: Any | None,
    cfg: Any,
    t_base_end: Any | None = None,
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
    if depth_mm is None:
        LOG.warning("无深度图：识别到的几何体统一使用 shapes.staging_area 坐标（仅自检场景合理）")
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < (h * w) * 0.005:
            continue
        perim = cv2.arcLength(cnt, True)
        if perim <= 0:
            continue
        circ = 4 * math.pi * area / (perim * perim)
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

        # ---------- 用点云做 6D 位姿估计 ----------
        if depth_mm is not None:
            # 1. 用轮廓的 bounding box 切出深度图区域
            x, y, w_box, h_box = cv2.boundingRect(cnt)
            pad = 10
            x0 = max(0, x - pad)
            y0 = max(0, y - pad)
            x1 = min(depth_mm.shape[1], x + w_box + pad)
            y1 = min(depth_mm.shape[0], y + h_box + pad)
            depth_roi = depth_mm[y0:y1, x0:x1].astype(np.float32)

            # 2. 生成点云（只取有效深度）
            rows, cols = depth_roi.shape
            u_coords, v_coords = np.meshgrid(np.arange(cols), np.arange(rows))
            depth_m = depth_roi / 1000.0
            valid = (depth_m > 0.1) & (depth_m < 5.0)
            if np.sum(valid) < 10:
                LOG.warning("形状块点云有效点太少，跳过该块")
                continue

            fx = float(cfg.camera.fx)
            fy = float(cfg.camera.fy)
            cx0 = float(cfg.camera.cx)
            cy0 = float(cfg.camera.cy)

            x_c = (u_coords[valid] - cx0) * depth_m[valid] / fx
            y_c = (v_coords[valid] - cy0) * depth_m[valid] / fy
            z_c = depth_m[valid]
            pts_cam = np.stack([x_c, y_c, z_c], axis=1)

            # 3. 调用位姿估计（相机坐标系下）
            pose_cam = estimate_6d_pose(pts_cam)

            # 4. 手眼变换 → 机械臂基座坐标
            he = np.array(cfg.hand_eye.matrix, dtype=np.float64)
            p_cam = np.array([
                pose_cam["position"][0],
                pose_cam["position"][1],
                pose_cam["position"][2],
                1.0
            ])
            p_base = he @ p_cam

            pick = Pose(
                float(p_base[0]),
                float(p_base[1]),
                float(p_base[2]),
                pose_cam["orientation"][0],  # roll
                pose_cam["orientation"][1],  # pitch
                pose_cam["orientation"][2]   # yaw
            )
        else:
            # 无深度图时回退到 staging 区域（仅自检场景）
            pick = staging_pose(staging, "shapes.staging_area")

        out.append(_Shape(block_id=f"shape_{i}", shape=shape, pick=pick))
        if len(out) >= 16:
            break
    return out
