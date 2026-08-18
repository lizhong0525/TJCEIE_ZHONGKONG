from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from .models import RGBDFrame, VisionError

LOG = logging.getLogger(__name__)


class Gemini335Camera:
    """Gemini335 RGB-D采集：帧同步、深度到彩色D2C对齐、真实深度比例。"""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.pipeline = None
        self.align_filter = None
        self.intrinsics: tuple[float, float, float, float] | None = None
        self.serial_number = ""
        self._lock = threading.Lock()

    @staticmethod
    def _sdk():
        try:
            import pyorbbecsdk as sdk  # type: ignore
        except ImportError as exc:
            raise VisionError("未安装pyorbbecsdk2，无法连接Gemini335") from exc
        return sdk

    def start(self) -> None:
        if self.pipeline is not None:
            return
        sdk = self._sdk()
        context = sdk.Context()
        devices = context.query_devices()
        count = devices.get_count()
        if count <= 0:
            raise VisionError("没有发现Orbbec相机，请检查USB3、电源、驱动和SDK")

        wanted = str(self.settings.get("serial_number", "")).strip()
        device = None
        available: list[str] = []
        for index in range(count):
            candidate = devices.get_device_by_index(index)
            serial = str(candidate.get_device_info().get_serial_number())
            available.append(serial)
            if not wanted or serial == wanted:
                device = candidate
                self.serial_number = serial
                if wanted:
                    break
        if device is None:
            raise VisionError(f"未找到相机序列号 {wanted}；已连接 {available}")

        try:
            self.pipeline = sdk.Pipeline(device)
        except TypeError:
            if wanted and count > 1:
                raise VisionError("当前SDK不能按序列号创建Pipeline，请只连接目标相机")
            self.pipeline = sdk.Pipeline()

        config = sdk.Config()
        color_profiles = self.pipeline.get_stream_profile_list(sdk.OBSensorType.COLOR_SENSOR)
        color_profile = color_profiles.get_video_stream_profile(0, 0, sdk.OBFormat.RGB, 0)
        depth_profiles = self.pipeline.get_stream_profile_list(sdk.OBSensorType.DEPTH_SENSOR)
        depth_profile = depth_profiles.get_default_video_stream_profile()
        config.enable_stream(color_profile)
        config.enable_stream(depth_profile)
        config.set_frame_aggregate_output_mode(sdk.OBFrameAggregateOutputMode.FULL_FRAME_REQUIRE)

        try:
            self.pipeline.enable_frame_sync()
            LOG.info("Gemini335 彩色/深度帧同步已启用")
        except Exception as exc:  # SDK/固件不支持时必须显式告警
            LOG.warning("相机帧同步未启用，需现场检查时间戳: %s", exc)
        self.align_filter = sdk.AlignFilter(align_to_stream=sdk.OBStreamType.COLOR_STREAM)
        self.pipeline.start(config)

        frame = None
        for _ in range(30):
            frame = self._wait_aligned()
            if frame is not None:
                break
        if frame is None:
            self.stop()
            raise VisionError("相机启动后30次仍未取得对齐的彩色+深度帧")

        params = self.pipeline.get_camera_param()
        rgb = params.rgb_intrinsic
        self.intrinsics = (float(rgb.fx), float(rgb.fy), float(rgb.cx), float(rgb.cy))

        for _ in range(int(self.settings.get("warmup_frames", 20))):
            self._wait_aligned()

    def stop(self) -> None:
        if self.pipeline is not None:
            try:
                self.pipeline.stop()
            finally:
                self.pipeline = None

    def _wait_aligned(self):
        if self.pipeline is None or self.align_filter is None:
            raise VisionError("相机尚未启动")
        timeout = int(self.settings.get("frame_timeout_ms", 1500))
        frames = self.pipeline.wait_for_frames(timeout)
        if not frames:
            return None
        aligned = self.align_filter.process(frames)
        if not aligned:
            return None
        return aligned.as_frame_set()

    def capture(self) -> RGBDFrame:
        if self.pipeline is None:
            self.start()
        if self.intrinsics is None:
            raise VisionError("相机内参未读取")
        with self._lock:
            frames = self._wait_aligned()
        if frames is None:
            raise VisionError("等待对齐RGB-D帧超时")
        color = frames.get_color_frame()
        depth = frames.get_depth_frame()
        if not color or not depth:
            raise VisionError("对齐帧中缺少彩色或深度数据")

        h, w = int(color.get_height()), int(color.get_width())
        rgb = np.frombuffer(color.get_data(), dtype=np.uint8)
        if rgb.size != h * w * 3:
            raise VisionError(f"彩色帧长度异常: {rgb.size} != {h*w*3}")
        rgb = rgb.reshape(h, w, 3)
        color_bgr = np.ascontiguousarray(rgb[:, :, ::-1])

        dh, dw = int(depth.get_height()), int(depth.get_width())
        raw = np.frombuffer(depth.get_data(), dtype=np.uint16)
        if raw.size != dh * dw:
            raise VisionError("深度帧长度异常")
        depth_mm = raw.reshape(dh, dw).astype(np.float32)
        depth_mm *= float(depth.get_depth_scale())
        minimum = float(self.settings.get("min_depth_mm", 100))
        maximum = float(self.settings.get("max_depth_mm", 2000))
        depth_mm[(depth_mm < minimum) | (depth_mm > maximum)] = 0.0
        if depth_mm.shape != color_bgr.shape[:2]:
            raise VisionError(
                f"D2C后尺寸不一致: color={color_bgr.shape[:2]} depth={depth_mm.shape}"
            )
        return RGBDFrame(color_bgr=color_bgr, depth_mm=depth_mm, intrinsics=self.intrinsics)

    def __enter__(self) -> "Gemini335Camera":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()
