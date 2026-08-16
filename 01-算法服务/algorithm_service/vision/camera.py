"""Gemini335 视觉封装。

* 优先用 ``pyorbbecsdk`` 官方 Python 绑定（彩色 + 深度 + 内参）。
* 未安装 SDK 时：``capture()`` 抛 ``VisionError``；调用方应在赛题层转换为
  ``{"success": false, "message": "camera not ready"}``。
* 提供 ``pixel_to_base``：像素+深度 → 相机坐标 →
  ``t_base_end(拍照时刻) @ t_end_camera(hand_eye)`` → 基座系 (m)。
  矩阵非法（占位/未标定）或缺 ``t_base_end`` 时抛 ``VisionError``，绝不静默猜坐标。

设计为**单例**容器 ``Vision``，由应用层在启动时实例化一次。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

LOG = logging.getLogger(__name__)

try:  # 可选依赖；未安装时降级为不可用
    import pyorbbecsdk as ob  # type: ignore
    _HAVE_OBSDK = True
except Exception:  # noqa: BLE001
    ob = None  # type: ignore
    _HAVE_OBSDK = False


class VisionError(RuntimeError):
    """视觉采集或处理失败。"""


@dataclass
class Frame:
    color: np.ndarray  # BGR, HxWx3 uint8
    depth: np.ndarray | None  # uint16, HxW, mm
    intrinsics: tuple[float, float, float, float]  # fx, fy, cx, cy
    distortion: tuple[float, float, float, float]  # k1, k2, p1, p2


class Vision:
    def __init__(
        self,
        intrinsics: tuple[float, float, float, float] = (0, 0, 0, 0),
        distortion: tuple[float, float, float, float] = (0, 0, 0, 0),
        hand_eye: list[list[float]] | None = None,
        max_consecutive_failures: int = 3,
    ) -> None:
        self.intrinsics = self._to_float_tuple(intrinsics, length=4)
        self.distortion = self._to_float_tuple(distortion, length=4)
        # 手眼矩阵非法（占位/非数值）时**不**退回单位矩阵——静默用错坐标比报错危险得多。
        # 用 None 显式标记"未标定"：capture 照常可用，pixel_to_base 直接拒绝。
        try:
            self.hand_eye = np.array(hand_eye, dtype=np.float64) if hand_eye else None
        except (TypeError, ValueError):
            LOG.warning("hand_eye 含占位/非数值项，坐标解算功能不可用（capture 不受影响）")
            self.hand_eye = None
        self._max_fail = max_consecutive_failures
        self._consecutive_failures = 0
        self.health_ready = True
        self._lock = threading.Lock()
        self._pipeline = None
        self._init_sdk()

    @staticmethod
    def _to_float_tuple(values: Any, length: int) -> tuple[float, ...]:
        out: list[float] = []
        for v in values:
            if isinstance(v, str):
                try:
                    out.append(float(v))
                except ValueError:
                    out.append(0.0)
            elif v is None:
                out.append(0.0)
            else:
                out.append(float(v))
        while len(out) < length:
            out.append(0.0)
        return tuple(out[:length])

    # ---- SDK 初始化 -------------------------------------------------------

    def _init_sdk(self) -> None:
        if not _HAVE_OBSDK:
            LOG.warning("pyorbbecsdk 未安装；视觉不可用。赛题将返回 camera not ready。")
            self.health_ready = False
            return
        try:
            self._pipeline = ob.Pipeline()
            cfg = ob.Config()
            # 启用彩色 + 深度
            try:
                color_profile = self._pipeline.get_stream_profile_list(ob.OBSensorType.COLOR_SENSOR).get_default_video_stream_profile()
                cfg.enable_stream(color_profile)
            except Exception as e:  # noqa: BLE001
                LOG.warning("启用彩色流失败: %s", e)
            try:
                depth_profile = self._pipeline.get_stream_profile_list(ob.OBSensorType.DEPTH_SENSOR).get_default_video_stream_profile()
                cfg.enable_stream(depth_profile)
            except Exception as e:  # noqa: BLE001
                LOG.warning("启用深度流失败: %s", e)
            self._pipeline.start(cfg)
            LOG.info("Orbbec Pipeline 已启动")
        except Exception as e:  # noqa: BLE001
            LOG.error("Orbbec Pipeline 启动失败: %s", e)
            self._pipeline = None
            self.health_ready = False

    def close(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pipeline = None

    # ---- 采集 -------------------------------------------------------------

    def capture(self, timeout_ms: int = 1000) -> Frame:
        if self._pipeline is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_fail:
                self.health_ready = False
            raise VisionError("Orbbec pipeline 未启动（pyorbbecsdk 未安装或设备未连接）")
        with self._lock:
            try:
                frames = self._pipeline.wait_for_frames(timeout_ms)
            except Exception as e:  # noqa: BLE001
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._max_fail:
                    self.health_ready = False
                raise VisionError(f"采集失败: {e}") from e
        self._consecutive_failures = 0

        color = self._bgr_from(frames)
        depth = self._depth_from(frames)
        if color is None:
            raise VisionError("未拿到彩色帧")
        return Frame(
            color=color,
            depth=depth,
            intrinsics=self.intrinsics,
            distortion=self.distortion,
        )

    @staticmethod
    def _bgr_from(frames: Any) -> np.ndarray | None:
        if frames is None:
            return None
        color = frames.get_color_frame() if hasattr(frames, "get_color_frame") else None
        if color is None:
            return None
        try:
            import cv2  # type: ignore
        except Exception:  # noqa: BLE001
            return np.frombuffer(color.get_data(), dtype=np.uint8).reshape(
                color.get_height(), color.get_width(), 3
            )
        data = np.asanyarray(color.get_data())
        return cv2.cvtColor(data, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _depth_from(frames: Any) -> np.ndarray | None:
        if frames is None:
            return None
        depth = frames.get_depth_frame() if hasattr(frames, "get_depth_frame") else None
        if depth is None:
            return None
        return np.frombuffer(depth.get_data(), dtype=np.uint16).reshape(
            depth.get_height(), depth.get_width()
        )

    # ---- 手眼变换 ---------------------------------------------------------

    def pixel_to_base(
        self,
        u: float,
        v: float,
        depth_m: float,
        t_base_end: Any | None = None,
    ) -> tuple[float, float, float]:
        """像素 (u, v) + 深度 (m) → 基座系 (x, y, z) (m)。

        手眼链（eye-in-hand，与 04-相机 一致）：
        ``p_base = t_base_end(拍照时刻末端位姿) @ t_end_camera(self.hand_eye) @ p_cam``。
        ``hand_eye`` 填 04 ``solve_hand_eye`` 输出的 ``t_end_camera`` 原值即可；
        ``t_base_end`` 每次解算都要用拍照时刻的 ``GET /api/pose`` 重算（随臂动变化）。
        缺任一环直接抛 ``VisionError``，绝不静默用单位矩阵或猜坐标。
        """

        fx, fy, cx, cy = self.intrinsics
        if fx <= 0 or fy <= 0:
            raise VisionError("相机内参未标定（fx/fy=0）")
        if self.hand_eye is None:
            raise VisionError("手眼矩阵未标定（hand_eye 是占位/非数值），拒绝解算坐标")
        if t_base_end is None:
            raise VisionError("缺拍照时刻末端位姿 t_base_end（eye-in-hand 链需要 /api/pose），拒绝解算坐标")
        x_c = (u - cx) * depth_m / fx
        y_c = (v - cy) * depth_m / fy
        p_cam = np.array([x_c, y_c, depth_m, 1.0], dtype=np.float64)
        try:
            t_be = np.array(t_base_end, dtype=np.float64)
        except (TypeError, ValueError) as e:
            raise VisionError(f"t_base_end 含非数值项，拒绝解算坐标: {e}") from e
        p_base = t_be @ self.hand_eye @ p_cam
        return float(p_base[0]), float(p_base[1]), float(p_base[2])
