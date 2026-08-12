from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

import _bootstrap  # noqa: F401
from vision.config import ROOT, load_config, validate_config
from vision.geometry import deproject_pixel, pixel_to_base, pose_xyzrpy_to_matrix, robust_depth_at
from vision.models import CameraIntrinsics
from vision.table_plane import fit_plane_ransac
from vision.task1 import detect_lit_lamp


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main() -> int:
    # 自检不访问真机，固定读取可入库的模板，CI/新电脑无需先创建真实配置。
    config = load_config(ROOT / "config.example.json")
    validate_config(config)
    check(True, "配置结构")
    check(config["camera"]["min_depth_mm"] < config["camera"]["max_depth_mm"], "配置深度范围")
    intr = CameraIntrinsics(640, 480, 600, 600, 320, 240, (0, 0, 0, 0, 0))
    center = deproject_pixel(320, 240, 1000, intr)
    check(np.allclose(center, [0, 0, 1]), "中心像素反投影")
    depth = np.zeros((480, 640), dtype=np.float32)
    depth[238:243, 318:323] = 1000
    check(robust_depth_at(depth, 320, 240, 2) == 1000, "局部中值深度")
    identity_pose = pose_xyzrpy_to_matrix([0, 0, 0, 0, 0, 0])
    base = pixel_to_base(320, 240, depth, intr, identity_pose, np.eye(4))
    check(np.allclose(base, [0, 0, 1]), "相机点转换到基座")
    rng = np.random.default_rng(7)
    xy = rng.uniform(-0.3, 0.3, size=(1200, 2))
    z = 0.7 + rng.normal(0, 0.001, size=(1200, 1))
    points = np.hstack((xy, z))
    outliers = rng.uniform(-1, 1, size=(100, 3))
    plane = fit_plane_ransac(np.vstack((points, outliers)), threshold_m=0.004)
    check(plane.inlier_ratio > 0.85, "RANSAC台面平面拟合")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "intrinsics.json"
        path.write_text(json.dumps(intr.to_dict()), encoding="utf-8")
        check(path.stat().st_size > 0, "结果JSON可写")
    try:
        detect_lit_lamp(np.zeros((20, 20, 3), dtype=np.uint8), config)
    except RuntimeError as error:
        check("尚未完成现场标定" in str(error), "任务一未标定时拒绝识别")
    else:
        raise AssertionError("任务一ROI未标定却继续识别")
    try:
        import cv2  # noqa: F401
        print("INFO OpenCV已安装，可运行识别与手眼标定")
    except ImportError:
        print("SKIP OpenCV未安装：真机识别工具暂不可运行")
    try:
        import pyorbbecsdk  # noqa: F401
        print("INFO pyorbbecsdk已安装，可连接Gemini335")
    except ImportError:
        print("SKIP pyorbbecsdk未安装：当前仅完成离线自检")
    print("OVERALL PASS（离线数学与配置部分）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
