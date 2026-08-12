from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LampDetection:
    target: str
    scores: dict[str, float]
    centers_px: dict[str, tuple[int, int]]
    confidence_margin: float


def _roi_pixels(shape: tuple[int, ...], roi: list[float]) -> tuple[int, int, int, int]:
    height, width = shape[:2]
    x0, y0, x1, y1 = roi
    return int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height)


def detect_lit_lamp(color_bgr: np.ndarray, config: dict) -> tuple[LampDetection, np.ndarray]:
    settings = config["task1"]
    rois = settings.get("lamp_rois_normalized", {})
    if not isinstance(rois, dict) or len(rois) < 2:
        raise RuntimeError(
            "task1.lamp_rois_normalized尚未完成现场标定；请填写每个候选灯的名称和归一化ROI"
        )
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("亮灯识别需要opencv-contrib-python") from error
    hsv = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2HSV)
    preview = color_bgr.copy()
    scores: dict[str, float] = {}
    centers: dict[str, tuple[int, int]] = {}
    for name, roi in rois.items():
        if not isinstance(roi, list) or len(roi) != 4:
            raise RuntimeError(f"{name} ROI必须是[x0,y0,x1,y1]四个归一化数字")
        x0, y0, x1, y1 = _roi_pixels(color_bgr.shape, roi)
        patch = hsv[y0:y1, x0:x1]
        if patch.size == 0:
            raise RuntimeError(f"{name} ROI无效，请修改config.json")
        value = patch[:, :, 2].astype(np.float32)
        saturation = patch[:, :, 1].astype(np.float32)
        bright_threshold = np.percentile(value, 90)
        bright = value[value >= bright_threshold]
        score = float(bright.mean() + 0.15 * saturation[value >= bright_threshold].mean())
        scores[name] = score
        centers[name] = ((x0 + x1) // 2, (y0 + y1) // 2)
    ranking = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    winner, winner_score = ranking[0]
    margin = winner_score - ranking[1][1]
    if winner_score < float(settings["minimum_brightness_score"]):
        raise RuntimeError(f"三个区域都不像亮灯：最高分{winner_score:.1f}")
    if margin < float(settings["minimum_winner_margin"]):
        raise RuntimeError(f"亮灯结果不唯一：前两名差值仅{margin:.1f}")
    for name, roi in rois.items():
        x0, y0, x1, y1 = _roi_pixels(color_bgr.shape, roi)
        color = (0, 255, 0) if name == winner else (120, 120, 120)
        cv2.rectangle(preview, (x0, y0), (x1, y1), color, 2)
        cv2.putText(preview, f"{name}: {scores[name]:.1f}", (x0, max(20, y0 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return LampDetection(winner, scores, centers, margin), preview
