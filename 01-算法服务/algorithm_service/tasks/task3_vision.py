"""赛题 3 视觉 —— 7.2 形状分类 + 7.3 点云位姿估计。

* 轮廓提取（Otsu→Canny→dilate）→ 7.2 规则四分类
  （``shape_classifier.classify_shape``：triangular_prism / hexagonal_prism /
  rectangular_prism / cylinder，类别名与 site.yaml ``shapes.kinds`` 对齐）。
* 坐标解算：有深度图时按轮廓遮罩出点云 → 7.3 质心 + PCA 主轴
  （``pose_estimator.estimate_6d_pose``）→ 手眼链
  ``t_base_end @ t_end_camera`` 转基座系；任一环节未标定抛 ``PickError``；
  无深度图回退 ``shapes.staging_area``（必须已标定，否则抛 ``PickError``；
  仅自检场景合理）。
* 物体姿态（PCA 主轴 RPY）目前只作识别记录（``_Shape.obj_rpy``）——运动链
  统一用 ``service.default_rpy`` 下爪，7.5 空中姿态校正接入时再用它。
* 返回 ``[_Shape(block_id, shape, pick, obj_rpy)]``。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..planner import Pose
from ._coords import cam_points_to_base, camera_intrinsics, staging_pose
from .pose_estimator import estimate_6d_pose
from .shape_classifier import classify_shape

LOG = logging.getLogger(__name__)


@dataclass
class _Shape:
    block_id: str
    shape: str
    pick: Pose
    obj_rpy: tuple[float, float, float] | None = None  # 物体主轴姿态（7.3 估计值，信息项）


def _object_points_cam(
    cnt: Any,
    depth_mm: Any,
    fx: float,
    fy: float,
    cx0: float,
    cy0: float,
) -> Any | None:
    """单个轮廓的点云（相机系，米）：外接矩形 ROI + 轮廓遮罩，只取有效深度。

    有效点 <10 返回 ``None``（调用方跳过该块，宁可漏识别也不用错坐标）。
    反投影必须用整图像素坐标——ROI 局部坐标要加回 bbox 偏移，
    否则主点 cx0/cy0 对不上（仓库 7.3 初版的坑之一）。
    """

    import cv2  # type: ignore
    import numpy as np  # type: ignore

    x, y, bw, bh = cv2.boundingRect(cnt)
    roi = depth_mm[y:y + bh, x:x + bw].astype(np.float32)
    if roi.size == 0:
        return None
    mask = np.zeros((bh, bw), np.uint8)
    cv2.fillPoly(mask, [cnt - np.array([[[x, y]]], dtype=cnt.dtype)], 255)
    valid = (mask > 0) & (roi > 100) & (roi < 5000)
    if int(np.count_nonzero(valid)) < 10:
        return None
    vv, uu = np.nonzero(valid)
    z = roi[valid] / 1000.0
    u_full = (uu + x).astype(np.float64)  # 加回 ROI 在整图中的偏移
    v_full = (vv + y).astype(np.float64)
    x_c = (u_full - cx0) * z / fx
    y_c = (v_full - cy0) * z / fy
    return np.stack([x_c, y_c, z], axis=1)


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
    intrinsics: tuple[float, float, float, float] | None = None
    if depth_mm is None:
        LOG.warning("无深度图：识别到的几何体统一使用 shapes.staging_area 坐标（仅自检场景合理）")
    else:
        # 有深度图就要解算基座坐标：内参先过守卫，缺标定直接抛 PickError，
        # 宁可任务失败也不往错的坐标动（手眼链守卫在 cam_points_to_base 里）
        intrinsics = camera_intrinsics(cfg)
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < (h * w) * 0.005:
            continue
        perim = cv2.arcLength(cnt, True)
        if perim <= 0:
            continue
        rect = cv2.minAreaRect(cnt)
        bw_, bh_ = rect[1]
        if min(bw_, bh_) < 25:
            continue

        shape, confidence, feat = classify_shape(cnt)

        obj_rpy: tuple[float, float, float] | None = None
        if depth_mm is not None:
            fx, fy, cx0, cy0 = intrinsics  # type: ignore[misc]
            pts_cam = _object_points_cam(cnt, depth_mm, fx, fy, cx0, cy0)
            if pts_cam is None:
                LOG.warning("形状块点云有效点太少，跳过该块（宁可漏识别也不用错坐标）")
                continue
            pose_cam = estimate_6d_pose(pts_cam)
            p_base = cam_points_to_base([pose_cam["position"]], cfg, t_base_end)[0]
            pick = Pose(float(p_base[0]), float(p_base[1]), float(p_base[2]))
            obj_rpy = tuple(float(a) for a in pose_cam["orientation"])
        else:
            pick = staging_pose(staging, "shapes.staging_area")
        LOG.info(
            "形状块 %d：%s (conf=%.2f 顶点=%.0f 圆度=%.3f) 抓取点=(%.3f,%.3f,%.3f) 物体姿态=%s",
            i, shape, confidence, feat["vertices"], feat["circularity"],
            pick.x, pick.y, pick.z,
            "无深度" if obj_rpy is None else "(%.2f,%.2f,%.2f)" % obj_rpy,
        )
        out.append(_Shape(block_id=f"shape_{i}", shape=shape, pick=pick, obj_rpy=obj_rpy))
        if len(out) >= 16:
            break
    return out
