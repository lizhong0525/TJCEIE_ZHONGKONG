"""赛题视觉共用的坐标解算保护。

历史问题：``float('__现场标定后填入__')`` 的裸 ``ValueError`` 会直接变成返回给
竞赛软件的 ``message``；手眼矩阵占位时 ``Vision`` 又静默退成单位矩阵，解算出
错误坐标还不报错。这里统一收口：**未标定 = 抛 ``PickError`` 指明缺什么**，
宁可失败也不往错的地方动。
"""
from __future__ import annotations

import logging
import math
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


def xyzrpy_to_matrix(pose: Any) -> list[list[float]]:
    """``{x,y,z,roll,pitch,yaw}`` → 4×4 齐次矩阵（XYZ 固定轴，等价 Rz(yaw)@Ry(pitch)@Rx(roll)）。

    与 04-相机 ``vision/geometry.py`` 的 ``pose_xyzrpy_to_matrix`` 同一约定，
    用来把 ``GET /api/pose`` 的响应转成 ``t_base_end``。
    """

    import numpy as np

    x, y, z, roll, pitch, yaw = (
        float(pose[k]) for k in ("x", "y", "z", "roll", "pitch", "yaw")
    )
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
    t = np.eye(4, dtype=np.float64)
    t[:3, :3] = rz @ ry @ rx
    t[:3, 3] = [x, y, z]
    return t.tolist()


def staging_pose(staging: Any, label: str) -> Pose:
    """无深度图时的兜底坐标：staging 区域中心必须已标定，否则抛清晰 ``PickError``。"""

    try:
        return pose_from_vec3(staging, label)
    except PickError as e:
        raise PickError(f"{e}（当前无可用深度图，视觉只能回退到该区域中心）") from e


def camera_intrinsics(cfg: Any) -> tuple[float, float, float, float]:
    """校验并返回 ``(fx, fy, cx, cy)``；fx/fy 占位时抛 ``PickError``。"""

    if is_placeholder(cfg.camera.fx) or is_placeholder(cfg.camera.fy):
        raise PickError("相机内参未标定（camera.fx/fy 仍是占位），无法解算基座坐标")
    return (
        float(cfg.camera.fx),
        float(cfg.camera.fy),
        float(cfg.camera.cx),
        float(cfg.camera.cy),
    )


def hand_eye_chain(cfg: Any, t_base_end: Any | None) -> tuple[Any, Any]:
    """校验手眼链并返回 ``(t_base_end, t_end_camera)`` 两个 4×4 numpy 矩阵。

    任一环节未标定/缺失都抛 ``PickError`` 指明缺什么——宁可报错也不猜坐标。
    """

    he = cfg.hand_eye.matrix
    if not he or is_placeholder(he[0][0]):
        raise PickError("手眼矩阵未标定（hand_eye.rows 仍是占位，应填 04 输出的 t_end_camera），无法解算基座坐标")
    if t_base_end is None:
        raise PickError("缺拍照时刻末端位姿 t_base_end（eye-in-hand 链需要拍照时读 /api/pose），拒绝猜坐标")

    import numpy as np

    try:
        t_end_camera = np.array(he, dtype=np.float64)
        t_be = np.array(t_base_end, dtype=np.float64)
    except (TypeError, ValueError) as e:
        raise PickError(f"手眼链含非数值项，无法解算基座坐标: {e}") from e
    return t_be, t_end_camera


def cam_points_to_base(
    points_cam: Any,
    cfg: Any,
    t_base_end: Any | None = None,
) -> Any:
    """相机系 Nx3 点集（米）→ 基座系 Nx3。标定校验同 ``pixel_to_base_pose``。

    7.3 点云位姿估计的质心、task2 单像素解算都走这一条链，保证全服务
    只有一处 ``t_base_end @ t_end_camera`` 约定。
    """

    import numpy as np

    t_be, t_end_camera = hand_eye_chain(cfg, t_base_end)
    pts = np.atleast_2d(np.asarray(points_cam, dtype=np.float64))
    pts_h = np.hstack([pts, np.ones((pts.shape[0], 1), dtype=np.float64)])
    return (t_be @ t_end_camera @ pts_h.T).T[:, :3]


def pixel_to_base_pose(
    u: float,
    v: float,
    depth_m: float,
    cfg: Any,
    t_base_end: Any | None = None,
) -> Pose:
    """像素 + 深度 → 基座系坐标。任一环节未标定都抛 ``PickError``。

    手眼链（eye-in-hand，与 04-相机 完全一致的约定）：
    ``p_base = t_base_end(拍照时刻末端位姿) @ t_end_camera(site.yaml hand_eye) @ p_cam``

    * site.yaml 的 ``hand_eye`` **直接填** 04 ``results/hand_eye.json`` 的
      ``t_end_camera``，不需要再乘任何链；
    * ``t_base_end`` 由调用方在拍照时刻读 ``GET /api/pose`` 取得——随臂动变化，
      不能写死进配置；缺了它宁可报错也不猜坐标。

    **纯数学计算，不构造 ``Vision``**：``Vision()`` 会 ``pipeline.start()`` 打开
    相机硬件流，历史上这里每解算一个块就新建一条管线且从不 close——真机上
    必漏资源。坐标解算只需要内参 + 手眼链，与采集完全无关。
    """

    fx, fy, cx0, cy0 = camera_intrinsics(cfg)
    x_c = (u - cx0) * depth_m / fx
    y_c = (v - cy0) * depth_m / fy
    p_base = cam_points_to_base([[x_c, y_c, depth_m]], cfg, t_base_end)[0]
    return Pose(float(p_base[0]), float(p_base[1]), float(p_base[2]))
