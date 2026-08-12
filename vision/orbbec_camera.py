from __future__ import annotations

import time
from typing import Any

import numpy as np

from .models import CameraIntrinsics, FrameBundle


class CameraUnavailable(RuntimeError):
    pass


class Gemini335Camera:
    """Gemini335彩色+深度采集器；深度以软件方式对齐到彩色图。"""

    def __init__(self, config: dict[str, Any]):
        self.settings = config["camera"]
        self.pipeline = None
        self.align_filter = None
        self.intrinsics: CameraIntrinsics | None = None
        self.serial_number = ""

    @staticmethod
    def _sdk():
        try:
            import pyorbbecsdk as sdk  # type: ignore
        except ImportError as error:
            raise CameraUnavailable(
                "未安装奥比中光Python SDK。请先安装pyorbbecsdk2，详见使用说明。"
            ) from error
        return sdk

    def start(self) -> None:
        sdk = self._sdk()
        context = sdk.Context()
        devices = context.query_devices()
        count = devices.get_count()
        if count == 0:
            raise CameraUnavailable("未发现奥比中光相机，请检查USB、电源、驱动和SDK")

        wanted = str(self.settings.get("serial_number", "")).strip()
        device = None
        available: list[str] = []
        for index in range(count):
            candidate = devices.get_device_by_index(index)
            serial = candidate.get_device_info().get_serial_number()
            available.append(serial)
            if not wanted or serial == wanted:
                device = candidate
                self.serial_number = serial
                if wanted:
                    break
        if device is None:
            raise CameraUnavailable(f"未找到序列号{wanted}；当前相机：{available}")

        try:
            self.pipeline = sdk.Pipeline(device)
        except TypeError:
            if wanted and count > 1:
                raise CameraUnavailable("当前SDK不支持按序列号创建Pipeline，请只连接目标相机")
            self.pipeline = sdk.Pipeline()

        stream_config = sdk.Config()
        color_profiles = self.pipeline.get_stream_profile_list(sdk.OBSensorType.COLOR_SENSOR)
        color_profile = color_profiles.get_video_stream_profile(0, 0, sdk.OBFormat.RGB, 0)
        depth_profiles = self.pipeline.get_stream_profile_list(sdk.OBSensorType.DEPTH_SENSOR)
        depth_profile = depth_profiles.get_default_video_stream_profile()
        stream_config.enable_stream(color_profile)
        stream_config.enable_stream(depth_profile)
        stream_config.set_frame_aggregate_output_mode(
            sdk.OBFrameAggregateOutputMode.FULL_FRAME_REQUIRE
        )
        try:
            self.pipeline.enable_frame_sync()
        except Exception:
            pass
        self.align_filter = sdk.AlignFilter(align_to_stream=sdk.OBStreamType.COLOR_STREAM)
        self.pipeline.start(stream_config)

        first = None
        for _ in range(30):
            first = self._wait_aligned_frames()
            if first is not None:
                break
        if first is None:
            self.stop()
            raise CameraUnavailable("相机已发现，但30次尝试仍未取得彩色+深度帧")

        params = self.pipeline.get_camera_param()
        rgb = params.rgb_intrinsic
        dist = params.rgb_distortion
        self.intrinsics = CameraIntrinsics(
            width=int(rgb.width),
            height=int(rgb.height),
            fx=float(rgb.fx),
            fy=float(rgb.fy),
            cx=float(rgb.cx),
            cy=float(rgb.cy),
            distortion=(float(dist.k1), float(dist.k2), float(dist.p1), float(dist.p2), float(dist.k3)),
        )

        for _ in range(int(self.settings.get("warmup_frames", 20))):
            self._wait_aligned_frames()

    def stop(self) -> None:
        if self.pipeline is not None:
            try:
                self.pipeline.stop()
            finally:
                self.pipeline = None

    def __enter__(self) -> "Gemini335Camera":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()

    def _wait_aligned_frames(self):
        if self.pipeline is None or self.align_filter is None:
            raise CameraUnavailable("相机尚未启动")
        timeout = int(self.settings.get("frame_timeout_ms", 1500))
        frames = self.pipeline.wait_for_frames(timeout)
        if not frames:
            return None
        aligned = self.align_filter.process(frames)
        if not aligned:
            return None
        return aligned.as_frame_set()

    def capture(self) -> FrameBundle:
        if self.intrinsics is None:
            raise CameraUnavailable("相机尚未启动或内参未就绪")
        frames = self._wait_aligned_frames()
        if frames is None:
            raise CameraUnavailable("等待彩色+深度对齐帧超时")
        color_frame = frames.get_color_frame()
        depth_frame = frames.get_depth_frame()
        if not color_frame or not depth_frame:
            raise CameraUnavailable("帧集中缺少彩色帧或深度帧")

        height, width = color_frame.get_height(), color_frame.get_width()
        rgb = np.frombuffer(color_frame.get_data(), dtype=np.uint8)
        expected = int(height) * int(width) * 3
        if rgb.size != expected:
            raise CameraUnavailable(
                f"彩色帧长度异常：期待{expected}，实际{rgb.size}；请核对SDK输出格式"
            )
        rgb = rgb.reshape((height, width, 3))
        color_bgr = np.ascontiguousarray(rgb[:, :, ::-1])

        dh, dw = depth_frame.get_height(), depth_frame.get_width()
        raw_depth = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
        if raw_depth.size != int(dh) * int(dw):
            raise CameraUnavailable("深度帧长度异常")
        depth_mm = raw_depth.reshape((dh, dw)).astype(np.float32)
        depth_mm *= float(depth_frame.get_depth_scale())
        minimum = float(self.settings.get("min_depth_mm", 100))
        maximum = float(self.settings.get("max_depth_mm", 2000))
        depth_mm[(depth_mm < minimum) | (depth_mm > maximum)] = 0.0
        if depth_mm.shape != color_bgr.shape[:2]:
            raise CameraUnavailable(
                f"D2C对齐后尺寸仍不一致：color={color_bgr.shape[:2]}, depth={depth_mm.shape}"
            )
        return FrameBundle(color_bgr, depth_mm, self.intrinsics, time.time())


def camera_summary(camera: Gemini335Camera) -> dict[str, Any]:
    if camera.intrinsics is None:
        raise CameraUnavailable("内参不存在")
    return {
        "camera_model": "Gemini335 / Gemini330 series",
        "serial_number": camera.serial_number,
        "depth_aligned_to": "color",
        "depth_unit": "mm",
        "color_intrinsics": camera.intrinsics.to_dict(),
    }
