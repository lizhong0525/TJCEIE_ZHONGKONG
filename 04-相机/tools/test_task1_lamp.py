from __future__ import annotations

from pathlib import Path

import _bootstrap  # noqa: F401
from vision.config import ROOT, load_config
from vision.orbbec_camera import Gemini335Camera
from vision.task1 import detect_lit_lamp


def main() -> int:
    try:
        import cv2
    except ImportError:
        print("缺少OpenCV")
        return 2
    config = load_config()
    with Gemini335Camera(config) as camera:
        frame = camera.capture()
    result, preview = detect_lit_lamp(frame.color_bgr, config)
    output = ROOT / "output" / "task1_lamp_preview.png"
    output.parent.mkdir(exist_ok=True)
    cv2.imwrite(str(output), preview)
    print(f"识别结果：{result.target}")
    print(f"分数：{result.scores}")
    print(f"预览：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
