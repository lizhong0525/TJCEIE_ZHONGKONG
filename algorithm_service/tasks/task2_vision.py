"""赛题 2 视觉识别 —— 数字长方体检测 + 数字 OCR。

最小可用版本（用于联调与自检）：

* 轮廓检测找矩形外接 → 计算 ``(u, v)`` 中心。
* 数字 OCR：用 tesseract（``D:\\OCR\\tesseract.exe``）的 ``--psm 8``（单字模式）。
* 深度存在时通过 ``Vision.pixel_to_base`` 转基座坐标；否则把 ``pick`` 设为
  ``cfg.digit_blocks.staging_area`` 的占位（便于在没有深度时自检流程）。

返回 ``[(block_id, digit, pick_pose)]``，其中 ``pick_pose`` 是基座系 Pose（m）。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


@dataclass
class _Detected:
    block_id: int
    digit: int
    pick: Any  # Pose


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
        depth_val = None
        if depth_mm is not None:
            yy, xx = cy, cx
            if 0 <= yy < depth_mm.shape[0] and 0 <= xx < depth_mm.shape[1]:
                d = int(depth_mm[yy, xx])
                if 100 < d < 5000:
                    depth_val = d / 1000.0  # m
        if depth_val is not None:
            try:
                from ..vision import Vision  # type: ignore
                # 注：调用方应传 Vision 实例的 pixel_to_base；这里以 cfg 内参做
                # 一次性构造（仅用于自检；真机请用 Vision 实例）。
                v = Vision(
                    intrinsics=(cfg.camera.fx, cfg.camera.fy, cfg.camera.cx, cfg.camera.cy),
                    distortion=(cfg.distortion.k1, cfg.distortion.k2, cfg.distortion.p1, cfg.distortion.p2),
                    hand_eye=cfg.hand_eye.matrix,
                )
                bx, by, bz = v.pixel_to_base(cx, cy, depth_val)
            except Exception as e:  # noqa: BLE001
                LOG.debug("手眼变换失败，使用 staging_area: %s", e)
                bx, by, bz = float(staging.x), float(staging.y), float(staging.z)
        else:
            bx, by, bz = float(staging.x), float(staging.y), float(staging.z)

        from ..planner import Pose  # 避免循环
        out.append(_Detected(block_id=block_id, digit=digit, pick=Pose(bx, by, bz)))
        block_id += 1
        if block_id >= 16:  # 安全上限
            break
    return out
