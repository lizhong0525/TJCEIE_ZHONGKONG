from __future__ import annotations

import math
from typing import Any

import numpy as np

from .models import Pose6D, VisionError


def rpy_to_matrix(pose: Pose6D) -> np.ndarray:
    cr, sr = math.cos(pose.roll), math.sin(pose.roll)
    cp, sp = math.cos(pose.pitch), math.sin(pose.pitch)
    cy, sy = math.cos(pose.yaw), math.sin(pose.yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
    out = np.eye(4, dtype=np.float64)
    out[:3, :3] = rz @ ry @ rx
    out[:3, 3] = [pose.x, pose.y, pose.z]
    return out


def valid_depth_m(depth_mm: Any, u: float, v: float, radius: int = 3) -> float:
    depth = np.asarray(depth_mm, dtype=np.float64)
    if depth.ndim != 2:
        raise VisionError("深度图必须是二维数组")
    x, y = int(round(u)), int(round(v))
    h, w = depth.shape
    patch = depth[max(0, y-radius):min(h, y+radius+1), max(0, x-radius):min(w, x+radius+1)]
    good = patch[(patch > 100) & (patch < 5000)]
    if good.size < 3:
        raise VisionError(f"像素({x},{y})附近没有足够有效深度")
    return float(np.median(good)) / 1000.0


def pixel_to_base(
    u: float,
    v: float,
    depth_m: float,
    intrinsics: tuple[float, float, float, float],
    t_base_end: np.ndarray,
    t_end_camera: np.ndarray,
) -> np.ndarray:
    fx, fy, cx, cy = (float(x) for x in intrinsics)
    if fx <= 0 or fy <= 0 or depth_m <= 0:
        raise VisionError("相机内参或深度无效")
    p_cam = np.array([
        (u-cx)*depth_m/fx,
        (v-cy)*depth_m/fy,
        depth_m,
        1.0,
    ], dtype=np.float64)
    return (t_base_end @ t_end_camera @ p_cam)[:3]


def pixel_axis_yaw_in_base(
    u: float,
    v: float,
    image_angle_rad: float,
    depth_m: float,
    intrinsics: tuple[float, float, float, float],
    t_base_end: np.ndarray,
    t_end_camera: np.ndarray,
) -> float:
    """把图像中的长轴方向转换为机械臂基座系yaw。"""

    step = 20.0
    p0 = pixel_to_base(u, v, depth_m, intrinsics, t_base_end, t_end_camera)
    p1 = pixel_to_base(
        u + step * math.cos(image_angle_rad),
        v + step * math.sin(image_angle_rad),
        depth_m,
        intrinsics,
        t_base_end,
        t_end_camera,
    )
    delta = p1 - p0
    if math.hypot(float(delta[0]), float(delta[1])) < 1e-6:
        raise VisionError("物体图像方向无法转换为基座yaw")
    yaw = math.atan2(float(delta[1]), float(delta[0]))
    # 长方体绕Z轴相差pi是同一姿态，统一到[-pi/2, pi/2)。
    while yaw >= math.pi / 2:
        yaw -= math.pi
    while yaw < -math.pi / 2:
        yaw += math.pi
    return yaw


def parse_hand_eye(rows: Any) -> np.ndarray:
    try:
        matrix = np.asarray(rows, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise VisionError("手眼矩阵含非数值") from exc
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise VisionError("手眼矩阵必须是有效4x4矩阵")
    if abs(float(np.linalg.det(matrix[:3, :3]))) < 0.5:
        raise VisionError("手眼矩阵旋转部分不可逆")
    return matrix
