from __future__ import annotations

import logging
import math
from typing import Any, Callable

import cv2
import numpy as np

from .config import DestinationSlot, RuntimeConfig, SourceSlot
from .geometry import (
    parse_hand_eye,
    pixel_axis_yaw_in_base,
    pixel_to_base,
    rpy_to_matrix,
    valid_depth_m,
)
from .models import BlockObservation, Pose6D, RGBDFrame, VisionError
from .ocr import DigitRecognizer

LOG = logging.getLogger(__name__)


def _roi_pixels(roi: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi
    return (
        max(0, min(width - 1, int(round(x0 * width)))),
        max(0, min(height - 1, int(round(y0 * height)))),
        max(1, min(width, int(round(x1 * width)))),
        max(1, min(height, int(round(y1 * height)))),
    )


def _order_quad(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums, diffs = pts.sum(axis=1), np.diff(pts, axis=1).reshape(-1)
    ordered[0] = pts[np.argmin(sums)]   # 左上
    ordered[2] = pts[np.argmax(sums)]   # 右下
    ordered[1] = pts[np.argmin(diffs)]  # 右上
    ordered[3] = pts[np.argmax(diffs)]  # 左下
    return ordered


def _extract_block_patch(
    color_bgr: np.ndarray,
    roi: tuple[float, float, float, float],
) -> tuple[np.ndarray, tuple[float, float], float]:
    """从一个固定物理槽ROI中找顶面并透视拉正，返回OCR图、全图中心、图像长轴角。"""

    h, w = color_bgr.shape[:2]
    x0, y0, x1, y1 = _roi_pixels(roi, w, h)
    crop = color_bgr[y0:y1, x0:x1]
    if crop.size == 0:
        raise VisionError(f"槽位ROI为空: {roi}")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 35, 110)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    minimum = crop.shape[0] * crop.shape[1] * 0.08
    candidates = [cnt for cnt in contours if cv2.contourArea(cnt) >= minimum]
    if not candidates:
        # 仍允许OCR整槽内部区域，但置信度门禁会阻止错误运动。
        inset_x, inset_y = max(2, crop.shape[1] // 10), max(2, crop.shape[0] // 10)
        patch = crop[inset_y:crop.shape[0]-inset_y, inset_x:crop.shape[1]-inset_x]
        return patch, ((x0+x1)/2.0, (y0+y1)/2.0), 0.0

    contour = max(candidates, key=cv2.contourArea)
    rect = cv2.minAreaRect(contour)
    (cx, cy), (rw, rh), angle_deg = rect
    if rw < 8 or rh < 8:
        raise VisionError("检测到的方块顶面过小")
    box = _order_quad(cv2.boxPoints(rect))
    out_w, out_h = 180, 140
    dst = np.array([[0, 0], [out_w-1, 0], [out_w-1, out_h-1], [0, out_h-1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(box, dst)
    patch = cv2.warpPerspective(crop, matrix, (out_w, out_h))
    inset = 8
    patch = patch[inset:-inset, inset:-inset]

    # OpenCV角度转为长轴在图像中的方向。
    if rw < rh:
        angle_deg += 90.0
    angle_rad = math.radians(angle_deg)
    return patch, (x0 + float(cx), y0 + float(cy)), angle_rad


def _median_depth_in_roi(depth_mm: Any, roi: tuple[float, float, float, float]) -> float:
    depth = np.asarray(depth_mm, dtype=np.float64)
    if depth.ndim != 2:
        raise VisionError("验证所需深度图无效")
    h, w = depth.shape
    x0, y0, x1, y1 = _roi_pixels(roi, w, h)
    patch = depth[y0:y1, x0:x1]
    good = patch[(patch > 100) & (patch < 5000)]
    if good.size < 10:
        raise VisionError(f"ROI {roi} 有效深度不足")
    return float(np.median(good))


class Task2Vision:
    def __init__(self, camera: Any, recognizer: DigitRecognizer, config: RuntimeConfig):
        self.camera = camera
        self.recognizer = recognizer
        self.config = config

    def _observe_once(
        self,
        arm_pose: Pose6D,
    ) -> tuple[list[BlockObservation], RGBDFrame]:
        frame = self.camera.capture()
        task = self.config.task
        use_rgbd = bool(task.get("use_rgbd_refinement", False))
        offset = tuple(float(v) for v in task.get("rgbd_pick_offset_xyz_m", [0, 0, 0]))
        yaw_offset = float(task.get("gripper_yaw_offset_rad", 0.0))
        # 固定槽位模式只使用现场示教的抓取位，不依赖手眼标定。
        # 只有明确开启RGB-D精修时才解析手眼矩阵，避免占位参数误参与计算。
        if use_rgbd:
            t_base_end = rpy_to_matrix(arm_pose)
            t_end_camera = parse_hand_eye(self.config.raw["calibration"]["t_end_camera"])

        observations: list[BlockObservation] = []
        for slot in self.config.source_slots:
            patch, center, image_angle = _extract_block_patch(frame.color_bgr, slot.roi)
            reading = self.recognizer.recognize(patch)
            if reading is None:
                continue
            if use_rgbd:
                depth_m = valid_depth_m(frame.depth_mm, center[0], center[1])
                point = pixel_to_base(
                    center[0], center[1], depth_m, frame.intrinsics, t_base_end, t_end_camera
                )
                yaw = pixel_axis_yaw_in_base(
                    center[0], center[1], image_angle, depth_m,
                    frame.intrinsics, t_base_end, t_end_camera,
                ) + yaw_offset
                pick_pose = Pose6D(
                    float(point[0] + offset[0]),
                    float(point[1] + offset[1]),
                    float(point[2] + offset[2]),
                    slot.pick_pose.roll,
                    slot.pick_pose.pitch,
                    yaw,
                )
            else:
                pick_pose = slot.pick_pose
                yaw = slot.pick_pose.yaw
            observations.append(BlockObservation(
                digit=reading.digit,
                source_slot_id=slot.slot_id,
                pixel_center=center,
                confidence=reading.confidence,
                method=reading.method,
                pick_pose=pick_pose,
                source_yaw=yaw,
            ))
        return observations, frame

    def acquire_complete_mapping(
        self,
        arm_pose_provider: Callable[[], Pose6D],
    ) -> list[BlockObservation]:
        retries = max(1, int(self.config.task.get("recognition_attempts", 3)))
        required = {1, 2, 3, 4}
        best: list[BlockObservation] = []
        for attempt in range(1, retries + 1):
            observations, _ = self._observe_once(arm_pose_provider())
            digits = [item.digit for item in observations]
            exact = len(observations) == 4 and set(digits) == required and len(set(digits)) == 4
            LOG.info("任务二第%d次识别: %s", attempt, [(x.source_slot_id, x.digit, x.confidence) for x in observations])
            if exact:
                return sorted(observations, key=lambda item: item.digit)
            if len(set(digits)) > len({x.digit for x in best}):
                best = observations
        got = sorted({x.digit for x in best})
        raise VisionError(f"重拍{retries}次后仍未得到唯一完整数字集合 {{1,2,3,4}}，最好结果={got}；拒绝猜数字")

    def verify_transfer(
        self,
        source: SourceSlot,
        destination: DestinationSlot,
        expected_digit: int,
    ) -> None:
        verify = self.config.task.get("verification") or {}
        if not bool(verify.get("enabled", True)):
            LOG.warning("动作后视觉验证已关闭")
            return
        if destination.roi is None or source.empty_depth_mm is None or destination.empty_depth_mm is None:
            raise VisionError("动作后验证配置不完整")

        frame = self.camera.capture()
        source_depth = _median_depth_in_roi(frame.depth_mm, source.roi)
        destination_depth = _median_depth_in_roi(frame.depth_mm, destination.roi)
        empty_tol = float(verify.get("source_empty_tolerance_mm", 12.0))
        occupied_delta = float(verify.get("destination_occupied_min_delta_mm", 15.0))
        if abs(source_depth - source.empty_depth_mm) > empty_tol:
            raise VisionError(
                f"源槽 {source.slot_id} 未确认变空: 当前{source_depth:.1f}mm 空槽基准{source.empty_depth_mm:.1f}mm"
            )
        if destination_depth > destination.empty_depth_mm - occupied_delta:
            raise VisionError(
                f"放置点{expected_digit}未确认有物体: 当前{destination_depth:.1f}mm 空台基准{destination.empty_depth_mm:.1f}mm"
            )
        if bool(verify.get("verify_destination_digit", True)):
            patch, _, _ = _extract_block_patch(frame.color_bgr, destination.roi)
            reading = self.recognizer.recognize(patch)
            if reading is None or reading.digit != expected_digit:
                raise VisionError(
                    f"放置点未确认数字{expected_digit}，实际={None if reading is None else reading.digit}"
                )
