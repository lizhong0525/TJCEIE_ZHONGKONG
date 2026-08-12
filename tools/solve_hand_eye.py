from __future__ import annotations

import json

import _bootstrap  # noqa: F401
from vision.config import ROOT, load_config, resolve_project_path, save_json
from vision.hand_eye import observation_from_dict, solve_eye_in_hand


def main() -> int:
    config = load_config()
    samples_path = ROOT / "data" / "hand_eye" / "samples.json"
    if not samples_path.exists():
        print("没有手眼样本。请先运行 tools/collect_hand_eye.py")
        return 2
    raw = json.loads(samples_path.read_text(encoding="utf-8"))
    minimum = int(config["calibration"]["minimum_hand_eye_samples"])
    if len(raw) < minimum:
        print(f"样本不足：当前{len(raw)}，至少需要{minimum}")
        return 2
    result = solve_eye_in_hand([observation_from_dict(item) for item in raw])
    quality = result["quality"]
    limits = config["calibration"]
    passed = (
        quality["max_reprojection_error_px"] <= float(limits["maximum_reprojection_error_px"])
        and quality["max_target_translation_spread_m"] <= float(limits["maximum_translation_spread_m"])
    )
    result["quality_gate_passed"] = passed
    result["quality_limits"] = {
        "maximum_reprojection_error_px": limits["maximum_reprojection_error_px"],
        "maximum_translation_spread_m": limits["maximum_translation_spread_m"],
    }
    output = resolve_project_path(limits["hand_eye_result"])
    save_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"结果已保存：{output}")
    if not passed:
        print("质量门禁未通过：不得用于真机运动，请重新采样标定。")
        return 3
    print("质量门禁通过。仍需使用独立已知点做现场验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
