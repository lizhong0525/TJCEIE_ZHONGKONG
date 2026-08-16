from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import CameraIntrinsics


@dataclass(frozen=True)
class PlaneResult:
    normal: np.ndarray
    d: float
    inlier_ratio: float
    point_count: int

    def to_dict(self) -> dict:
        return {
            "equation": "n.x + d = 0",
            "normal": self.normal.tolist(),
            "d_m": float(self.d),
            "inlier_ratio": float(self.inlier_ratio),
            "point_count": int(self.point_count),
        }


def depth_roi_to_points(
    depth_mm: np.ndarray,
    intr: CameraIntrinsics,
    roi_normalized: list[float],
    step: int = 6,
) -> np.ndarray:
    height, width = depth_mm.shape
    x0, y0, x1, y1 = roi_normalized
    u0, u1 = int(x0 * width), int(x1 * width)
    v0, v1 = int(y0 * height), int(y1 * height)
    vv, uu = np.mgrid[v0:v1:step, u0:u1:step]
    z = depth_mm[vv, uu].astype(np.float64) / 1000.0
    valid = np.isfinite(z) & (z > 0)
    z, uu, vv = z[valid], uu[valid], vv[valid]
    x = (uu - intr.cx) * z / intr.fx
    y = (vv - intr.cy) * z / intr.fy
    return np.column_stack((x, y, z))


def fit_plane_ransac(
    points: np.ndarray,
    iterations: int = 500,
    threshold_m: float = 0.004,
    seed: int = 2026,
) -> PlaneResult:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 30:
        raise ValueError("拟合平面至少需要30个有效三维点")
    rng = np.random.default_rng(seed)
    best_mask = None
    for _ in range(iterations):
        sample = points[rng.choice(len(points), 3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        length = np.linalg.norm(normal)
        if length < 1e-9:
            continue
        normal /= length
        d = -float(normal @ sample[0])
        mask = np.abs(points @ normal + d) <= threshold_m
        if best_mask is None or int(mask.sum()) > int(best_mask.sum()):
            best_mask = mask
    if best_mask is None or best_mask.sum() < 3:
        raise ValueError("RANSAC未找到稳定平面")
    inliers = points[best_mask]
    center = inliers.mean(axis=0)
    _, _, vh = np.linalg.svd(inliers - center, full_matrices=False)
    normal = vh[-1]
    normal /= np.linalg.norm(normal)
    if normal[2] > 0:
        normal = -normal
    d = -float(normal @ center)
    return PlaneResult(normal, d, float(best_mask.mean()), len(points))
