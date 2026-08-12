"""赛题 1 视觉检测 —— 6 按钮亮灯识别。

最小可用版本：HSV 颜色阈值 + 圆度 + 面积过滤。参数来自
``config/vision/task1.yaml``（运行时首次读取，文件不存在时使用内置默认）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "roi_radius": 40,                 # 按钮中心 ROI 半径（像素）
    "min_area_ratio": 0.05,           # 高亮像素 / ROI 面积 最小比例
    "min_circularity": 0.55,          # 圆度阈值（4πA/P²）
    "colors": {                       # HSV 范围
        "red":    [[[0, 90, 80],   [10, 255, 255]], [[170, 90, 80], [180, 255, 255]]],
        "yellow": [[[20, 90, 80],  [35, 255, 255]]],
        "green":  [[[40, 70, 70],  [85, 255, 255]]],
    },
    "panel_view": {"u0": 100, "v0": 100, "u1": 700, "v1": 500},  # 面板粗定位窗口
}

_PARAMS: dict[str, Any] | None = None


def load_params(path: str | Path | None = None) -> dict[str, Any]:
    global _PARAMS
    if _PARAMS is not None:
        return _PARAMS
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "vision" / "task1.yaml"
    p = Path(path)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        LOG.info("task1 视觉参数 %s 不存在，使用内置默认", p)
        data = {}
    merged = {**DEFAULT_PARAMS, **data}
    _PARAMS = merged
    return merged


def detect_lit_buttons(
    color_bgr: Any,
    buttons: list[Any],
    params: dict[str, Any],
) -> list[str]:
    """返回当前"亮灯"按钮的 ``name`` 列表。"""

    import cv2  # 局部导入
    import numpy as np  # 局部导入

    hsv = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2HSV)
    panel = params.get("panel_view") or {}
    u0 = int(panel.get("u0", 0))
    v0 = int(panel.get("v0", 0))
    u1 = int(panel.get("u1", color_bgr.shape[1] - 1))
    v1 = int(panel.get("v1", color_bgr.shape[0] - 1))

    h, w = hsv.shape[:2]
    u0 = max(0, min(w - 1, u0))
    u1 = max(0, min(w - 1, u1))
    v0 = max(0, min(h - 1, v0))
    v1 = max(0, min(h - 1, v1))
    if u1 <= u0 or v1 <= v0:
        return []

    detected: list[str] = []
    radius = int(params.get("roi_radius", 40))
    min_area_ratio = float(params.get("min_area_ratio", 0.05))
    min_circ = float(params.get("min_circularity", 0.55))
    colors = params.get("colors") or {}

    for btn in buttons:
        # 用按钮 name 索引的颜色做阈值；若按钮有独立 color 字段则按其选色
        cname = getattr(btn, "color", "red")
        ranges = colors.get(cname) or colors.get("red") or []
        if not ranges:
            continue
        # 像素中心无法直接知道：默认 ROI 取 panel_view 中心，按钮次序映射
        # 真实场景：按钮坐标由配置给出（基座系），需先做手眼反变换；这里给
        # 最小骨架 —— 用 panel_view 内的等分列定位。
        if len(buttons) <= 0:
            continue
        idx = next((i for i, b in enumerate(buttons) if b.name == btn.name), 0)
        col = idx % 3  # 三列布局：左中右
        row = idx // 3  # 上下两行
        x0 = u0 + (u1 - u0) * col // 3 + 8
        x1 = u0 + (u1 - u0) * (col + 1) // 3 - 8
        y0 = v0 + (v1 - v0) * row // 2 + 8
        y1 = v0 + (v1 - v0) * (row + 1) // 2 - 8
        cx = (x0 + x1) // 2
        cy = (y0 + y1) // 2
        x0r = max(0, cx - radius)
        y0r = max(0, cy - radius)
        x1r = min(w, cx + radius)
        y1r = min(h, cy + radius)
        roi = hsv[y0r:y1r, x0r:x1r]
        if roi.size == 0:
            continue
        mask = np.zeros(roi.shape[:2], dtype=np.uint8)
        for lo, hi in ranges:
            mask |= cv2.inRange(roi, np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))
        area = int(mask.sum() // 255)
        roi_area = max(1, mask.size)
        if area / roi_area < min_area_ratio:
            continue
        # 圆度
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        perim = cv2.arcLength(cnt, True)
        if perim <= 0:
            continue
        circ = 4 * 3.14159 * cv2.contourArea(cnt) / (perim * perim)
        if circ < min_circ:
            continue
        detected.append(btn.name)
    return detected
