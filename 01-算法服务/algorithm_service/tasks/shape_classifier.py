"""赛题 3 形状分类（7.2）—— 自 ``grasp_sorting_project`` 移植的规则四分类。

正式比赛物体（轮廓近似多边形特征判别）：

1. ``triangular_prism``  三棱柱
2. ``hexagonal_prism``   正六棱柱
3. ``rectangular_prism`` 长方体
4. ``cylinder``          圆柱体

当前为 RGB 二维轮廓 baseline（circularity / fill_ratio / solidity / vertices），
与 7.2 交付版逻辑保持一致；现场图像集验证后再按实测调阈值。
"""
from __future__ import annotations

from typing import Any

import cv2  # type: ignore
import numpy as np  # type: ignore

# =========================
# 比赛正式物体类别
# =========================

LABEL_TRIANGULAR_PRISM = "triangular_prism"
LABEL_HEXAGONAL_PRISM = "hexagonal_prism"
LABEL_RECTANGULAR_PRISM = "rectangular_prism"
LABEL_CYLINDER = "cylinder"


def extract_features(contour: np.ndarray) -> dict[str, float]:
    """从二维轮廓中提取基础几何特征（面积/周长/外接框/圆度/凸包/顶点数）。"""

    area = float(cv2.contourArea(contour))
    perimeter = float(cv2.arcLength(contour, True))

    x, y, w, h = cv2.boundingRect(contour)

    bbox_area = float(max(w * h, 1))
    fill_ratio = area / bbox_area

    circularity = 0.0
    if perimeter > 1e-6:
        circularity = (
            4.0 * np.pi * area / (perimeter * perimeter)
        )

    hull = cv2.convexHull(contour)
    hull_area = float(max(cv2.contourArea(hull), 1.0))

    solidity = area / hull_area

    aspect_ratio = (
        max(w, h) / max(min(w, h), 1)
    )

    approx = cv2.approxPolyDP(
        contour,
        0.02 * perimeter,
        True
    )

    return {
        "width": float(w),
        "height": float(h),
        "aspect_ratio": float(aspect_ratio),
        "fill_ratio": float(fill_ratio),
        "circularity": float(circularity),
        "solidity": float(solidity),
        "vertices": float(len(approx)),
    }


def classify_shape(
    contour: np.ndarray,
    confidence_threshold: float = 0.55,
) -> tuple[str, float, dict[str, float]]:
    """当前版本：RGB 二维轮廓 baseline。

    主要利用 circularity / fill_ratio / solidity / vertices；
    后续加入 Depth 特征提高真实场景鲁棒性。
    """

    features = extract_features(contour)

    circularity = features["circularity"]
    fill_ratio = features["fill_ratio"]
    solidity = features["solidity"]
    vertices = int(features["vertices"])

    # ---------------------------------
    # 1. 圆柱体
    # ---------------------------------
    #
    # 圆形轮廓受到少量噪声后：
    # circularity 可能下降，
    # vertices 也可能发生变化。
    #
    # 因此不能只依赖 vertices。
    #
    if (
        circularity >= 0.90
        and fill_ratio >= 0.74
        and vertices >= 7
    ):
        confidence = min(
            0.98,
            0.55
            + 0.35
            * min(
                (circularity - 0.90) / 0.10,
                1.0,
            ),
        )

        return (
            LABEL_CYLINDER,
            confidence,
            features,
        )

    # ---------------------------------
    # 2. 三棱柱
    # ---------------------------------
    #
    # 当前 baseline：
    # 轮廓明显接近三角形时，
    # 判断为三棱柱。
    #
    if vertices == 3:
        confidence = min(
            0.90,
            0.60 + 0.30 * solidity,
        )

        return (
            LABEL_TRIANGULAR_PRISM,
            confidence,
            features,
        )

    # ---------------------------------
    # 3. 正六棱柱
    # ---------------------------------
    #
    # 真实图像存在噪声时，
    # 六边形经过 approxPolyDP 后
    # 可能变成 7～8 个顶点。
    #
    # 因此不能只判断 vertices == 6。
    #
    if (
        6 <= vertices <= 8
        and circularity < 0.96
        and fill_ratio < 0.74
    ):
        confidence = min(
            0.90,
            0.60
            + 0.30
            * (
                0.5 * solidity
                + 0.5 * (1.0 - circularity)
            ),
        )

        return (
            LABEL_HEXAGONAL_PRISM,
            confidence,
            features,
        )

    # ---------------------------------
    # 4. 长方体
    # ---------------------------------
    #
    # 当前二维 baseline：
    # 四边形默认认为是长方体。
    #
    if vertices == 4:
        confidence = min(
            0.90,
            0.60 + 0.30 * solidity,
        )

        return (
            LABEL_RECTANGULAR_PRISM,
            confidence,
            features,
        )

    # ---------------------------------
    # 5. 无法确定
    # ---------------------------------
    #
    # 当前暂时保留原有 fallback，
    # 后续正式比赛建议改成 unknown，
    # 并拒绝抓取。
    #
    return (
        LABEL_RECTANGULAR_PRISM,
        confidence_threshold,
        features,
    )
