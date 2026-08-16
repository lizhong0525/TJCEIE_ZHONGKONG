from __future__ import annotations

import argparse
import json

import _bootstrap  # noqa: F401
from vision.config import ROOT, load_config, resolve_project_path


def status() -> int:
    config = load_config()
    intrinsics = resolve_project_path(config["calibration"]["intrinsics_result"])
    hand_eye = resolve_project_path(config["calibration"]["hand_eye_result"])
    table = ROOT / "results" / "table_plane_camera.json"
    checks = {
        "相机内参": intrinsics,
        "眼在手上手眼标定": hand_eye,
        "台面平面": table,
    }
    complete = True
    for name, path in checks.items():
        state = "已有" if path.exists() else "缺少"
        print(f"{state:4} {name}: {path}")
        complete = complete and path.exists()
    if hand_eye.exists():
        value = json.loads(hand_eye.read_text(encoding="utf-8"))
        if not value.get("quality_gate_passed", False):
            print("警告：手眼标定文件存在，但质量门禁未通过")
            complete = False
    print("\n下一步顺序：")
    print("1. python tools/check_camera.py")
    print("2. python tools/export_intrinsics.py")
    print("3. python tools/collect_hand_eye.py")
    print("4. python tools/solve_hand_eye.py")
    print("5. python tools/fit_table_plane.py")
    print("6. 使用独立已知点验证基座坐标误差")
    return 0 if complete else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="中控杯视觉标定总入口")
    parser.add_argument("command", nargs="?", default="status", choices=["status"])
    parser.parse_args()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
