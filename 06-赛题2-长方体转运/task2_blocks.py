from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class NumberBlock:
    digit: int | None
    center_px: tuple[int, int]
    box: tuple[int, int, int, int]
    area_px: float
    angle_deg: float


# ---------------------------------------------------------------------------
# OCR：与 01-算法服务 tasks/task2_vision.py 同一套做法
# （候选 exe 必须带 eng.traineddata；临时图写系统临时目录；2x 放大 + 阈值 + --psm 8）
# ---------------------------------------------------------------------------


def _tessdata_ok(exe: str) -> bool:
    """该 tesseract 是否有可用的 eng 语言数据（没有会在 OCR 时报 Failed loading language）。"""

    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix and (Path(prefix) / "eng.traineddata").exists():
        return True
    return (Path(exe).parent / "tessdata" / "eng.traineddata").exists()


def _tesseract_cmd(settings: dict) -> str | None:
    # 显式配置优先；候选：历史约定 D:\OCR、PATH、常见安装目录
    # **必须带 eng.traineddata 才算可用**（本机 D:\OCR 的 tessdata 只有 chi_sim，曾导致 OCR 静默全灭）
    candidates = [
        settings.get("tesseract_command"),
        r"D:\OCR\tesseract.exe",
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    ]
    seen: set[str] = set()
    for cand in candidates:
        if cand and cand not in seen and Path(cand).exists():
            seen.add(cand)
            if _tessdata_ok(cand):
                return cand
    for cand in seen:  # 都不带 eng 数据时退而求其次，至少试跑
        LOG.warning("tesseract %s 缺少 tessdata/eng.traineddata，OCR 可能失败", cand)
        return cand
    return None


def _ocr_patch(roi_bgr: np.ndarray, cmd: str) -> int | None:
    import cv2

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)
    # 临时文件必须放系统临时目录——写 cv2 安装目录在只读环境（赛方工控机）会静默失败
    fd, tmp = tempfile.mkstemp(suffix="_digit_roi.png")
    os.close(fd)
    if not cv2.imwrite(tmp, bw):
        LOG.warning("OCR 临时图写入失败：%s", tmp)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None
    try:
        out = subprocess.run(
            [cmd, tmp, "-", "--psm", "8", "-c", "tessedit_char_whitelist=0123456789"],
            capture_output=True, text=True, timeout=5,
        )
        txt = (out.stdout or "").strip()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if not txt:
        return None
    try:
        return int(txt[0])
    except ValueError:
        return None


def detect_number_blocks(color_bgr: np.ndarray, config: dict) -> tuple[list[NumberBlock], np.ndarray]:
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("数字块识别需要opencv-contrib-python") from error
    settings = config["task2"]
    gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 60, 160)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    preview = color_bgr.copy()
    results: list[NumberBlock] = []
    tess_cmd = _tesseract_cmd(settings)
    if tess_cmd is None:
        LOG.warning("未找到可用 tesseract，数字 OCR 跳过（只检轮廓）")
    img_h, img_w = color_bgr.shape[:2]
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if not float(settings["minimum_block_area_px"]) <= area <= float(settings["maximum_block_area_px"]):
            continue
        rect = cv2.minAreaRect(contour)
        (cx, cy), (rw, rh), angle = rect
        if min(rw, rh) < 15:
            continue
        ratio = max(rw, rh) / max(1.0, min(rw, rh))
        if ratio > 3.5:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        digit = None
        if tess_cmd is not None:
            # 中心紧致裁剪（与 01 的 task2_vision 一致）：只取块面内部，
            # 把块边框和暗色背景挡在外面——整快带背景喂 OCR 会读出空白
            side = int(max(w, h) * 0.6)
            ccx, ccy = int(cx), int(cy)
            x0 = max(0, ccx - side // 2)
            y0 = max(0, ccy - side // 2)
            x1 = min(img_w, ccx + side // 2)
            y1 = min(img_h, ccy + side // 2)
            crop = color_bgr[y0:y1, x0:x1]
            if crop.size:
                digit = _ocr_patch(crop, tess_cmd)
                if digit is not None and digit not in (1, 2, 3, 4):
                    digit = None  # 赛题 2 只有 1-4
        results.append(NumberBlock(digit, (int(cx), int(cy)), (x, y, w, h), area, float(angle)))
        cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 200, 255), 2)
        cv2.putText(preview, str(digit) if digit else "?", (x, max(20, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
    return sorted(results, key=lambda item: item.center_px[0]), preview
