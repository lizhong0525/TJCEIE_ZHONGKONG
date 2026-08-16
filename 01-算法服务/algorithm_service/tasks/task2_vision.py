"""赛题 2 视觉识别 —— 数字长方体检测 + 数字 OCR。

最小可用版本（用于联调与自检）：

* 轮廓检测找矩形外接 → 计算 ``(u, v)`` 中心。
* 数字 OCR：用 tesseract（``D:\\OCR\\tesseract.exe``）的 ``--psm 8``（单字模式）。
* 深度有效时通过 ``Vision.pixel_to_base`` 转基座坐标；无深度图时回退
  ``digit_blocks.staging_area``（必须已标定，否则抛 ``PickError``；仅自检场景合理）。

返回 ``[(block_id, digit, pick_pose)]``，其中 ``pick_pose`` 是基座系 Pose（m）。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..planner import Pose
from ._coords import center_depth_m, pixel_to_base_pose, staging_pose

LOG = logging.getLogger(__name__)


@dataclass
class _Detected:
    block_id: int
    digit: int
    pick: Pose


def _tesseract_cmd() -> str | None:
    # 优先用户提供的 D:\OCR\tesseract.exe，否则 PATH
    for cand in (r"D:\OCR\tesseract.exe", shutil.which("tesseract")):
        if cand and Path(cand).exists():
            return cand
    return None


def _ocr_patch(roi_bgr: Any) -> int | None:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)
    cmd = _tesseract_cmd()
    if cmd is None:
        LOG.debug("tesseract 不可用，跳过 OCR")
        return None
    tmp = Path(cv2.__file__).parent / "_digit_roi.png"
    cv2.imwrite(str(tmp), bw)
    try:
        out = subprocess.run(
            [cmd, str(tmp), "-", "--psm", "8", "-c", "tessedit_char_whitelist=0123456789"],
            capture_output=True, text=True, timeout=5,
        )
        txt = (out.stdout or "").strip()
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    if not txt:
        return None
    try:
        return int(txt[0])
    except ValueError:
        return None


def recognize_digits(
    color_bgr: Any,
    depth_mm: Any | None,
    cfg: Any,
) -> list[_Detected]:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    if color_bgr is None:
        return []

    gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 60, 180)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = color_bgr.shape[:2]
    out: list[_Detected] = []
    block_id = 0
    staging = cfg.digit_blocks.staging_area
    if depth_mm is None:
        LOG.warning("无深度图：识别到的块统一使用 digit_blocks.staging_area 坐标（仅自检场景合理）")
    for cnt in contours:
        if cv2.contourArea(cnt) < (h * w) * 0.005:
            continue
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect)
        bw_, bh_ = rect[1]
        if bw_ < 30 or bh_ < 30:
            continue
        ratio = max(bw_, bh_) / min(bw_, bh_)
        if ratio > 3.0:  # 太长条的不算
            continue
        cx, cy = int(rect[0][0]), int(rect[0][1])
        side = int(max(bw_, bh_) * 0.6)
        x0 = max(0, cx - side // 2)
        y0 = max(0, cy - side // 2)
        x1 = min(w, cx + side // 2)
        y1 = min(h, cy + side // 2)
        roi = color_bgr[y0:y1, x0:x1]
        if roi.size == 0:
            continue
        digit = _ocr_patch(roi)
        if digit is None:
            continue

        # 深度 → 基座坐标
        depth_val = center_depth_m(depth_mm, cx, cy)
        if depth_val is not None:
            pick = pixel_to_base_pose(cx, cy, depth_val, cfg)
        elif depth_mm is not None:
            LOG.warning("块中心 (%d,%d) 深度无效，跳过该块（宁可漏识别也不用错坐标）", cx, cy)
            continue
        else:
            pick = staging_pose(staging, "digit_blocks.staging_area")

        out.append(_Detected(block_id=block_id, digit=digit, pick=pick))
        block_id += 1
        if block_id >= 16:  # 安全上限
            break
    return out
