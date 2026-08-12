from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from vision.config import load_config
from vision.geometry import robust_depth_at
from vision.orbbec_camera import Gemini335Camera, camera_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="检查Gemini335并显示彩色/深度画面")
    parser.add_argument("--save", action="store_true", help="保存当前彩色图和16位深度图")
    args = parser.parse_args()
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("缺少OpenCV，请先运行：python -m pip install -r requirements.txt")
        return 2
    config = load_config()
    output = Path(__file__).resolve().parents[1] / "output"
    output.mkdir(exist_ok=True)
    with Gemini335Camera(config) as camera:
        print(json.dumps(camera_summary(camera), ensure_ascii=False, indent=2))
        print("窗口中绿色十字为中心深度；按S保存，按Q或ESC退出。")
        while True:
            frame = camera.capture()
            view = frame.color_bgr.copy()
            h, w = view.shape[:2]
            u, v = w // 2, h // 2
            try:
                depth = robust_depth_at(frame.depth_mm, u, v, 2)
                text = f"center depth: {depth:.1f} mm"
            except ValueError:
                text = "center depth: INVALID"
            cv2.drawMarker(view, (u, v), (0, 255, 0), cv2.MARKER_CROSS, 24, 2)
            cv2.putText(view, text, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow("Gemini335 | S=save Q=quit", view)
            key = cv2.waitKey(1) & 0xFF
            if args.save or key in (ord("s"), ord("S")):
                cv2.imwrite(str(output / "color.png"), frame.color_bgr)
                cv2.imwrite(str(output / "depth_mm.png"), np.clip(frame.depth_mm, 0, 65535).astype(np.uint16))
                print(f"已保存到：{output}")
                args.save = False
            if key in (ord("q"), ord("Q"), 27):
                break
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
