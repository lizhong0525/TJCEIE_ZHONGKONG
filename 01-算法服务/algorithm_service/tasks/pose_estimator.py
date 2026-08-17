"""赛题 3 点云 6D 位姿估计（7.3）：质心 + PCA 主轴。

输入 Nx3 点云（同一坐标系，单位米），输出：

* ``position``    质心 [x, y, z]（抓取点候选）
* ``orientation`` 姿态 [roll, pitch, yaw]（弧度）——把参考 Z 轴旋转到
  物体主轴（协方差最大特征向量）所需的旋转，按 XYZ 固定轴
  （``R = Rz(yaw) @ Ry(pitch) @ Rx(roll)``，与 ``_coords`` 同一约定）解出。

纯 numpy 实现：原仓库版本依赖 scipy，现场工控机离线部署依赖已冻结，
``pyproject.toml`` 不新增包。旋转构造（Rodrigues）与欧拉角解算等价。
"""
from __future__ import annotations

import math

import numpy as np  # type: ignore


def estimate_6d_pose(pointcloud: np.ndarray) -> dict:
    """``pointcloud`` Nx3 → ``{"position": [...], "orientation": [r, p, y]}``。"""

    pts = np.asarray(pointcloud, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or pts.shape[0] < 3:
        raise ValueError(f"pointcloud 需为 Nx3 且 N>=3，实际 {pts.shape}")

    # 1. 位置估计：点云质心（抓取点）
    centroid = pts.mean(axis=0)

    # 2. 姿态估计：PCA 主轴。协方差是实对称矩阵，用 eigh（特征值升序、
    #    保证实数），最大特征向量 = 物体"长轴"方向。
    cov = np.cov((pts - centroid).T)
    _, eigenvectors = np.linalg.eigh(cov)
    main_axis = eigenvectors[:, -1]
    if main_axis[2] < 0:
        # 主轴方向有正负二义，统一取朝上分量，保证输出确定性
        main_axis = -main_axis

    # 3. 主轴 → 欧拉角：构造"把世界 Z 轴旋到 main_axis"的旋转（Rodrigues），
    #    再按 XYZ 固定轴解出 RPY。
    z_axis = np.array([0.0, 0.0, 1.0])
    v = np.cross(z_axis, main_axis)
    s = float(np.linalg.norm(v))
    c = float(np.dot(z_axis, main_axis))
    if s < 1e-9:
        # main_axis 已与 Z 平行（上面已把方向统一朝上，不会反向）
        rot_matrix = np.eye(3)
    else:
        vx = np.array(
            [[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]]
        )
        rot_matrix = np.eye(3) + vx + vx @ vx * ((1.0 - c) / (s ** 2))

    roll, pitch, yaw = _matrix_to_rpy(rot_matrix)

    return {
        "position": centroid.tolist(),
        "orientation": [roll, pitch, yaw],
    }


def _matrix_to_rpy(rot: np.ndarray) -> tuple[float, float, float]:
    """``R = Rz(yaw) @ Ry(pitch) @ Rx(roll)`` 的逆解（XYZ 固定轴，弧度）。"""

    pitch = math.atan2(-float(rot[2, 0]), math.hypot(float(rot[0, 0]), float(rot[1, 0])))
    roll = math.atan2(float(rot[2, 1]), float(rot[2, 2]))
    yaw = math.atan2(float(rot[1, 0]), float(rot[0, 0]))
    return roll, pitch, yaw
