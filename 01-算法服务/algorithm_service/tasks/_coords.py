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
    """取深度图 ``(u, v)`` 处的深度（米）；无深度图/越界/无效值返回 ``None``。"""

    if depth_mm is None:
        return None
    if 0 <= v < depth_mm.shape[0] and 0 <= u < depth_mm.shape[1]:
        d = int(depth_mm[v, u])
        if 100 < d < 5000:
            return d / 1000.0
    return None


def staging_pose(staging: Any, label: str) -> Pose:
    """无深度图时的兜底坐标：staging 区域中心必须已标定，否则抛清晰 ``PickError``。"""

    try:
        return pose_from_vec3(staging, label)
    except PickError as e:
        raise PickError(f"{e}（当前无可用深度图，视觉只能回退到该区域中心）") from e


def pixel_to_base_pose(u: float, v: float, depth_m: float, cfg: Any) -> Pose:
    """像素 + 深度 → 基座系坐标。内参/手眼未标定时抛 ``PickError``。"""

    if is_placeholder(cfg.camera.fx) or is_placeholder(cfg.camera.fy):
        raise PickError("相机内参未标定（camera.fx/fy 仍是占位），无法解算基座坐标")
    he = cfg.hand_eye.matrix
    if not he or is_placeholder(he[0][0]):
        raise PickError("手眼矩阵未标定（hand_eye.rows 仍是占位），无法解算基座坐标")

    from ..vision import Vision  # 局部导入，避免循环

    v = Vision(
        intrinsics=(cfg.camera.fx, cfg.camera.fy, cfg.camera.cx, cfg.camera.cy),
        distortion=(cfg.distortion.k1, cfg.distortion.k2, cfg.distortion.p1, cfg.distortion.p2),
        hand_eye=cfg.hand_eye.matrix,
    )
    try:
        bx, by, bz = v.pixel_to_base(u, v, depth_m)
    except Exception as e:  # noqa: BLE001
        raise PickError(f"像素 ({u},{v}) 深度 {depth_m:.3f}m 手眼解算失败: {e}") from e
    return Pose(bx, by, bz)
