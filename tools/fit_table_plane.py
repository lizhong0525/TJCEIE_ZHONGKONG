from __future__ import annotations

import json

import _bootstrap  # noqa: F401
from vision.config import ROOT, load_config, save_json
from vision.orbbec_camera import Gemini335Camera
from vision.table_plane import depth_roi_to_points, fit_plane_ransac


def main() -> int:
    config = load_config()
    settings = config["table"]
    with Gemini335Camera(config) as camera:
        frame = camera.capture()
    points = depth_roi_to_points(
        frame.depth_mm,
        frame.intrinsics,
        settings["roi_normalized"],
        int(settings["sample_step_pixels"]),
    )
    result = fit_plane_ransac(
        points,
        int(settings["ransac_iterations"]),
        float(settings["inlier_threshold_m"]),
    )
    value = result.to_dict()
    value["coordinate_frame"] = "color_camera"
    value["passed"] = result.inlier_ratio >= float(settings["minimum_inlier_ratio"])
    output = ROOT / "results" / "table_plane_camera.json"
    save_json(output, value)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    if not value["passed"]:
        print("台面内点比例不足，不得采用该平面。请清空ROI或调整范围。")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
