from __future__ import annotations

import _bootstrap  # noqa: F401
from vision.config import load_config, resolve_project_path, save_json
from vision.orbbec_camera import Gemini335Camera, camera_summary


def main() -> int:
    config = load_config()
    output = resolve_project_path(config["calibration"]["intrinsics_result"])
    with Gemini335Camera(config) as camera:
        result = camera_summary(camera)
    save_json(output, result)
    print(f"内参已保存：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
