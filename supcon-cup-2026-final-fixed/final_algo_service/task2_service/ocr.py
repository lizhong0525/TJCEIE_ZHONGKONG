from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .models import DigitReading

LOG = logging.getLogger(__name__)
VALID_DIGITS = {1, 2, 3, 4}


def _foreground_canvas(image_bgr: np.ndarray, size: int = 96) -> tuple[np.ndarray, float] | None:
    if image_bgr is None or image_bgr.size == 0:
        return None
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 少数像素类视为数字笔画，并归一成白字黑底。
    white = bw > 0
    fg = white if int(white.sum()) <= white.size // 2 else ~white
    ys, xs = np.nonzero(fg)
    if len(xs) < 8:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    glyph = (fg[y0:y1+1, x0:x1+1].astype(np.uint8) * 255)
    h, w = glyph.shape
    if h < 4 or w < 2:
        return None
    aspect = float(w) / float(h)
    target = int(size * 0.72)
    scale = min(target / w, target / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    glyph = cv2.resize(glyph, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((size, size), dtype=np.uint8)
    ox, oy = (size - nw) // 2, (size - nh) // 2
    canvas[oy:oy+nh, ox:ox+nw] = glyph
    return canvas, aspect


def _templates(size: int = 96) -> dict[int, list[np.ndarray]]:
    result: dict[int, list[np.ndarray]] = {d: [] for d in VALID_DIGITS}
    font = cv2.FONT_HERSHEY_SIMPLEX
    for digit in sorted(VALID_DIGITS):
        for scale in (1.5, 1.8, 2.1, 2.4):
            for thickness in (2, 3, 4):
                canvas = np.zeros((size, size), dtype=np.uint8)
                text = str(digit)
                (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
                pos = ((size - tw) // 2, (size + th) // 2 - baseline // 2)
                cv2.putText(canvas, text, pos, font, scale, 255, thickness, cv2.LINE_AA)
                normalized = _foreground_canvas(cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR), size)
                if normalized is not None:
                    result[digit].append(normalized[0])
    return result


class DigitRecognizer:
    """EasyOCR、Tesseract、模板匹配三路识别；任何一路缺失都可明确降级。"""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self._easy_reader = None
        self._easy_attempted = False
        self._template_bank = _templates()

    def _easyocr(self):
        if self._easy_attempted:
            return self._easy_reader
        self._easy_attempted = True
        if not bool(self.settings.get("enable_easyocr", True)):
            return None
        try:
            import easyocr  # type: ignore
            model_dir = self.settings.get("easyocr_model_dir") or None
            self._easy_reader = easyocr.Reader(
                ["en"],
                gpu=bool(self.settings.get("easyocr_gpu", False)),
                model_storage_directory=model_dir,
                download_enabled=bool(self.settings.get("allow_model_download", False)),
            )
        except Exception as exc:
            LOG.warning("EasyOCR不可用，将使用Tesseract/模板: %s", exc)
            self._easy_reader = None
        return self._easy_reader

    def _tesseract(self) -> str | None:
        candidates = [
            self.settings.get("tesseract_command"),
            shutil.which("tesseract"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"D:\OCR\tesseract.exe",
        ]
        for value in candidates:
            if not value or not Path(value).exists():
                continue
            tessdata = Path(value).parent / "tessdata" / "eng.traineddata"
            prefix = os.environ.get("TESSDATA_PREFIX")
            if tessdata.exists() or (prefix and (Path(prefix) / "eng.traineddata").exists()):
                return str(value)
        return None

    @staticmethod
    def _parse_digit(text: str) -> int | None:
        cleaned = text.strip().upper().replace("I", "1").replace("L", "1").replace("|", "1")
        digits = re.sub(r"[^0-9]", "", cleaned)
        if len(digits) == 1 and int(digits) in VALID_DIGITS:
            return int(digits)
        return None

    def _read_easyocr(self, image_bgr: np.ndarray) -> DigitReading | None:
        reader = self._easyocr()
        if reader is None:
            return None
        try:
            rows = reader.readtext(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB), allowlist="1234")
        except Exception as exc:
            LOG.warning("EasyOCR识别异常: %s", exc)
            return None
        for row in sorted(rows, key=lambda x: float(x[2]), reverse=True):
            digit = self._parse_digit(str(row[1]))
            if digit is not None:
                return DigitReading(digit, max(0.0, min(1.0, float(row[2]))), "easyocr")
        return None

    def _read_tesseract(self, image_bgr: np.ndarray) -> DigitReading | None:
        exe = self._tesseract()
        if exe is None:
            return None
        normalized = _foreground_canvas(image_bgr)
        if normalized is None:
            return None
        fd, path = tempfile.mkstemp(suffix="_task2_digit.png")
        os.close(fd)
        try:
            cv2.imwrite(path, normalized[0])
            result = subprocess.run(
                [exe, path, "-", "-l", "eng", "--psm", "10", "-c", "tessedit_char_whitelist=1234"],
                capture_output=True,
                text=True,
                timeout=float(self.settings.get("tesseract_timeout_s", 5)),
            )
            digit = self._parse_digit(result.stdout or "")
            return None if digit is None else DigitReading(digit, 0.78, "tesseract")
        except Exception as exc:
            LOG.warning("Tesseract识别异常: %s", exc)
            return None
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _read_template(self, image_bgr: np.ndarray) -> DigitReading | None:
        normalized = _foreground_canvas(image_bgr)
        if normalized is None:
            return None
        canvas, aspect = normalized
        candidates = (1,) if aspect < float(self.settings.get("digit1_aspect_max", 0.5)) else (1, 2, 3, 4)
        best_digit, best_score = None, -1.0
        for digit in candidates:
            for template in self._template_bank[digit]:
                score = float(cv2.matchTemplate(canvas, template, cv2.TM_CCOEFF_NORMED)[0, 0])
                if score > best_score:
                    best_digit, best_score = digit, score
        threshold = float(self.settings.get("template_min_score", 0.42))
        if best_digit is None or best_score < threshold:
            return None
        return DigitReading(int(best_digit), max(0.0, min(1.0, best_score)), "template")

    def recognize(self, image_bgr: np.ndarray) -> DigitReading | None:
        readings = [
            value for value in (
                self._read_easyocr(image_bgr),
                self._read_tesseract(image_bgr),
                self._read_template(image_bgr),
            ) if value is not None
        ]
        if not readings:
            return None
        by_digit: dict[int, list[DigitReading]] = {}
        for item in readings:
            by_digit.setdefault(item.digit, []).append(item)
        # 两路一致优先；否则采用单路最高置信，但必须过现场阈值。
        ranked = sorted(
            by_digit.items(),
            key=lambda pair: (len(pair[1]), max(x.confidence for x in pair[1])),
            reverse=True,
        )
        digit, votes = ranked[0]
        confidence = max(x.confidence for x in votes)
        minimum = float(self.settings.get("minimum_confidence", 0.60))
        if confidence < minimum:
            return None
        method = "+".join(sorted({x.method for x in votes}))
        return DigitReading(digit, confidence, method)
