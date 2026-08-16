from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class ShapeObject:
    label: str
    center_px: tuple[int, int]
    area_px: float
    circularity: float
    vertices: int
    angle_deg: float


def detect_shapes(color_bgr: np.ndarray, config: dict) -> tuple[list[ShapeObject], np.ndarray]:
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("形状识别需要opencv-contrib-python") from error
    settings = config["task3"]
    gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    preview = color_bgr.copy()
    objects: list[ShapeObject] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if not float(settings["minimum_object_area_px"]) <= area <= float(settings["maximum_object_area_px"]):
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        circularity = 4.0 * math.pi * area / (perimeter * perimeter)
        approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        vertices = len(approx)
        rect = cv2.minAreaRect(contour)
        (cx, cy), (rw, rh), angle = rect
        ratio = max(rw, rh) / max(1.0, min(rw, rh))
        if circularity >= 0.82 and vertices >= 7:
            label = "circle_or_cylinder"
        elif vertices == 4 and ratio <= 1.20:
            label = "square"
        elif vertices == 4:
            label = "rectangle"
        elif vertices <= 6:
            label = "polyhedron"
        else:
            label = "unknown"
        objects.append(ShapeObject(label, (int(cx), int(cy)), area, circularity, vertices, float(angle)))
        cv2.drawContours(preview, [contour], -1, (255, 120, 0), 2)
        cv2.putText(preview, label, (int(cx), int(cy)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 120, 0), 2)
    return objects, preview
