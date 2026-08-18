"""赛题 1 视觉检测 —— 3 个指示灯的亮灯识别（ROI 制）。

真实赛制：面板 3 个灯（红/黄/绿），每次随机亮且只亮一个；每个灯的像素 ROI
由现场标定写入 ``cfg.panel.lamps[].roi``（拍照位下的 ``[u0, v0, u1, v1]``）。

亮灯判据（满足其一即算亮）：

1. 颜色通道：ROI 内命中该灯颜色 HSV 区间的像素比例 ≥ ``min_area_ratio``；
2. 亮度通道：ROI 灰度均值 ≥ ``bright_mean_min``（灯亮发白光也兜得住）。

**并列拒绝**：所有有效 ROI 都计分排名，前两名得分差 < ``minimum_winner_margin``
（默认 1.2，相对阈值倍数的无量纲尺度）时判"亮灯结果不唯一"并拒动——现场反光
两灯同亮时静默选错灯 = 30 分，宁可返回失败留第二次机会。并列/多灯超阈值都会
记 warning。
参数来自 ``config/vision/task1.yaml``（运行时首次读取，文件不存在用内置默认）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "min_area_ratio": 0.10,           # 命中颜色像素 / ROI 面积 的最小比例
    "bright_mean_min": 140,           # 亮度兜底：ROI 灰度均值阈值（0-255）
    "minimum_winner_margin": 1.2,     # 并列拒绝：前两名得分差下限（相对阈值倍数）
    "colors": {                       # HSV 范围
        "red":    [[[0, 90, 80],   [10, 255, 255]], [[170, 90, 80], [180, 255, 255]]],
        "yellow": [[[20, 90, 80],  [35, 255, 255]]],
        "green":  [[[40, 70, 70],  [85, 255, 255]]],
    },
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


def _valid_roi(roi: Any) -> bool:
    return (
        isinstance(roi, list)
        and len(roi) == 4
        and all(isinstance(v, int) and v >= 0 for v in roi)
        and roi[2] > roi[0]
        and roi[3] > roi[1]
    )


def detect_lit_lamp(
    color_bgr: Any,
    lamps: list[Any],
    params: dict[str, Any],
) -> tuple[str | None, list[str], str]:
    """返回 ``(亮灯 name 或 None, ROI 未标定的 lamp name 列表, 拒动原因)``。

    规则约定每次只亮一个灯。**所有**有效 ROI 都计分排名（不亮的也计分），
    前两名得分差 < ``minimum_winner_margin`` 时判并列：返回 ``(None, invalid, 原因)``，
    调用方按"亮灯结果不唯一"拒动——反光两灯同亮时静默选错灯比明确失败贵 30 分。
    """

    import cv2  # 局部导入
    import numpy as np  # 局部导入

    hsv = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
    h, w = hsv.shape[:2]

    min_area_ratio = float(params.get("min_area_ratio", 0.10))
    bright_mean_min = float(params.get("bright_mean_min", 140))
    min_margin = float(params.get("minimum_winner_margin", 1.2))
    colors = params.get("colors") or {}

    invalid: list[str] = []
    scored: list[tuple[str, float, bool]] = []  # (name, score, 是否超亮灯阈值)
    for lamp in lamps:
        name = getattr(lamp, "name", "")
        roi = getattr(lamp, "roi", None)
        if not _valid_roi(roi):
            invalid.append(name)
            continue
        u0, v0, u1, v1 = roi
        u0 = max(0, min(w - 1, u0))
        u1 = max(0, min(w, u1))
        v0 = max(0, min(h - 1, v0))
        v1 = max(0, min(h, v1))
        if u1 <= u0 or v1 <= v0:
            invalid.append(name)
            continue

        roi_hsv = hsv[v0:v1, u0:u1]
        roi_gray = gray[v0:v1, u0:u1]
        roi_area = roi_hsv.shape[0] * roi_hsv.shape[1]
        if roi_area <= 0:
            invalid.append(name)
            continue

        # 1. 颜色通道得分
        cname = getattr(lamp, "color", "red")
        ranges = colors.get(cname) or []
        mask = np.zeros(roi_hsv.shape[:2], dtype=np.uint8)
        for lo, hi in ranges:
            mask |= cv2.inRange(roi_hsv, np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))
        color_ratio = int(mask.sum() // 255) / roi_area

        # 2. 亮度通道得分
        mean_v = float(roi_gray.mean())

        lit = (color_ratio >= min_area_ratio) or (mean_v >= bright_mean_min)
        # 归一化得分：两通道各自相对阈值的倍数，取大者（不亮的灯也计分参与排名）
        score = max(
            color_ratio / max(min_area_ratio, 1e-6),
            mean_v / max(bright_mean_min, 1e-6),
        )
        LOG.info(
            "lamp %s(%s): color_ratio=%.3f mean_v=%.1f score=%.2f -> %s",
            name, cname, color_ratio, mean_v, score, "LIT" if lit else "off",
        )
        scored.append((name, score, lit))

    ranking = sorted(scored, key=lambda item: item[1], reverse=True)
    if not ranking or not ranking[0][2]:
        return None, invalid, ""

    winner, winner_score, _ = ranking[0]
    lit_names = [n for n, _, lit in ranking if lit]
    if len(lit_names) > 1:
        LOG.warning("多个灯同时超阈值：%s（反光？按并列拒绝复核）", lit_names)
    if len(ranking) >= 2:
        margin = winner_score - ranking[1][1]
        if margin < min_margin:
            reason = (
                f"亮灯结果不唯一：{winner} 与 {ranking[1][0]} 得分差仅 {margin:.2f} "
                f"< minimum_winner_margin={min_margin}（疑似反光/两灯同亮），拒绝操作"
            )
            LOG.warning(reason)
            return None, invalid, reason
    return winner, invalid, ""
