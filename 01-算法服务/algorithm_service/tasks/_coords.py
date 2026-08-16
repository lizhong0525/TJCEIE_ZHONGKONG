"""赛题视觉共用的坐标解算保护。

历史问题：``float('__现场标定后填入__')`` 的裸 ``ValueError`` 会直接变成返回给
竞赛软件的 ``message``；手眼矩阵占位时 ``Vision`` 又静默退成单位矩阵，解算出
错误坐标还不报错。这里统一收口：**未标定 = 抛 ``PickError`` 指明缺什么**，
宁可失败也不往错的地方动。
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import is_placeholder
from ..planner import PickError, Pose, pose_from_vec3

LOG = logging.getLogger(__name__)


def center_depth_m(depth_mm: Any, u: int, v: int) -> float | None:
    """取深度图 ``(u, v)`` 附近 5×5 窗口的有效深度中值（米）。

    单像素深度容易踩到空洞/飞点，与 04-相机 的取法对齐；无有效值返回 ``None``。
    """

    if depth_mm is None:
        return None
    import numpy as np

    h, w = depth_mm.shape[:2]
    x0, x1 = max(0, u - 2), min(w, u + 3)
    y0, y1 = max(0, v - 2), min(h, v + 3)
    if x1 <= x0 or y1 <= y0:
        return None
    patch = depth_mm[y0:y1, x0:x1].astype(np.float64)
    valid = patch[(patch > 100) & (patch < 5000)]
    if valid.size == 0:
        return None
    return float(np.median(valid)) / 1000.0


def staging_pose(staging: Any, label: str) -> Pose:
    """无深度图时的兜底坐标：staging 区域中心必须已标定，否则抛清晰 ``PickError``。"""

    try:
        return pose_from_vec3(staging, label)
    except PickError as e:
        raise PickError(f"{e}（当前无可用深度图，视觉只能回退到该区域中心）") from e


def pixel_to_base_pose(u: float, v: float, depth_m: float, cfg: Any) -> Pose:
    """像素 + 深度 → 基座系坐标。内参/手眼未标定时抛 ``PickError``。

    **纯数学计算，不构造 ``Vision``**：``Vision()`` 会 ``pipeline.start()`` 打开
    相机硬件流，历史上这里每解算一个块就新建一条管线且从不 close——真机上
    必漏资源。坐标解算只需要内参 + 手眼矩阵，与采集完全无关。
    """

    if is_placeholder(cfg.camera.fx) or is_placeholder(cfg.camera.fy):
        raise PickError("相机内参未标定（camera.fx/fy 仍是占位），无法解算基座坐标")
    he = cfg.hand_eye.matrix
    if not he or is_placeholder(he[0][0]):
        raise PickError("手眼矩阵未标定（hand_eye.rows 仍是占位），无法解算基座坐标")

    import numpy as np

    fx, fy = float(cfg.camera.fx), float(cfg.camera.fy)
    cx0, cy0 = float(cfg.camera.cx), float(cfg.camera.cy)
    x_c = (u - cx0) * depth_m / fx
    y_c = (v - cy0) * depth_m / fy
    z_c = depth_m
    p_cam = np.array([x_c, y_c, z_c, 1.0], dtype=np.float64)
    try:
        t = np.array(he, dtype=np.float64)
    except (TypeError, ValueError) as e:
        raise PickError(f"手眼矩阵含非数值项，无法解算基座坐标: {e}") from e
    p_base = t @ p_cam
    return Pose(float(p_base[0]), float(p_base[1]), float(p_base[2]))
