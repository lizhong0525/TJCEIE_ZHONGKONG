from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from .models import CameraIntrinsics


def rpy_xyz_fixed_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """FTArm文档所述XYZ固定轴欧拉角，等价于 Rz(yaw) @ Ry(pitch) @ Rx(roll)。"""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
    return rz @ ry @ rx


def pose_xyzrpy_to_matrix(pose: dict[str, float] | Iterable[float]) -> np.ndarray:
    if isinstance(pose, dict):
        values = [pose[key] for key in ("x", "y", "z", "roll", "pitch", "yaw")]
    else:
        values = list(pose)
    if len(values) != 6:
        raise ValueError("位姿必须包含 x,y,z,roll,pitch,yaw 六个值")
    x, y, z, roll, pitch, yaw = map(float, values)
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rpy_xyz_fixed_to_matrix(roll, pitch, yaw)
    transform[:3, 3] = [x, y, z]
    return transform


def transform_point(transform: np.ndarray, point_xyz: Iterable[float]) -> np.ndarray:
    point = np.asarray([*point_xyz, 1.0], dtype=np.float64)
    return (np.asarray(transform, dtype=np.float64) @ point)[:3]


def deproject_pixel(u: float, v: float, depth_mm: float, intr: CameraIntrinsics) -> np.ndarray:
    """将已去畸变、且深度已对齐到彩色图的像素转成彩色相机三维坐标（米）。"""
    if not np.isfinite(depth_mm) or depth_mm <= 0:
        raise ValueError("深度必须是大于0的毫米值")
    z = float(depth_mm) / 1000.0
    x = (float(u) - intr.cx) * z / intr.fx
    y = (float(v) - intr.cy) * z / intr.fy
    return np.array([x, y, z], dtype=np.float64)


def robust_depth_at(depth_mm: np.ndarray, u: int, v: int, radius: int = 2) -> float:
    height, width = depth_mm.shape[:2]
    x0, x1 = max(0, u - radius), min(width, u + radius + 1)
    y0, y1 = max(0, v - radius), min(height, v + radius + 1)
    values = np.asarray(depth_mm[y0:y1, x0:x1], dtype=np.float64)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0:
        raise ValueError(f"像素({u},{v})附近没有有效深度")
    return float(np.median(values))


def pixel_to_base(
    u: int,
    v: int,
    depth_mm: np.ndarray,
    intr: CameraIntrinsics,
    t_base_end: np.ndarray,
    t_end_camera: np.ndarray,
    depth_radius: int = 2,
) -> np.ndarray:
    depth = robust_depth_at(depth_mm, u, v, depth_radius)
    point_camera = deproject_pixel(u, v, depth, intr)
    return transform_point(np.asarray(t_base_end) @ np.asarray(t_end_camera), point_camera)


def matrix_to_json(transform: np.ndarray) -> list[list[float]]:
    matrix = np.asarray(transform, dtype=np.float64)
    if matrix.shape != (4, 4):
        raise ValueError("变换矩阵必须是4×4")
    return [[float(v) for v in row] for row in matrix]
