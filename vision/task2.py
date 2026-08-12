from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NumberBlock:
    digit: int | None
    center_px: tuple[int, int]
    box: tuple[int, int, int, int]
    area_px: float
    angle_deg: float


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
    use_ocr = False
    try:
        import pytesseract
        if settings.get("tesseract_command"):
            pytesseract.pytesseract.tesseract_cmd = settings["tesseract_command"]
        use_ocr = True
    except ImportError:
        pytesseract = None
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
        crop = gray[max(0, y):y + h, max(0, x):x + w]
        digit = None
        if use_ocr and crop.size:
            text = pytesseract.image_to_string(
                crop,
                config="--psm 10 -c tessedit_char_whitelist=1234",
                lang=settings.get("ocr_language", "eng"),
            ).strip()
            digit = int(text[0]) if text and text[0] in "1234" else None
        results.append(NumberBlock(digit, (int(cx), int(cy)), (x, y, w, h), area, float(angle)))
        cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 200, 255), 2)
        cv2.putText(preview, str(digit) if digit else "?", (x, max(20, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
    return sorted(results, key=lambda item: item.center_px[0]), preview
