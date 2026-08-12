from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else ROOT / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"缺少相机配置：{config_path}\n"
            "请先把 config.example.json 复制为 config.json，再填写现场参数。"
        )
    with config_path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    validate_config(config)
    return config


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def save_json(path: str | Path, value: Any) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return output


def validate_config(config: dict[str, Any]) -> None:
    required_sections = ("camera", "robot", "calibration", "table", "task1", "task2", "task3")
    missing = [name for name in required_sections if not isinstance(config.get(name), dict)]
    if missing:
        raise ValueError(f"相机配置缺少对象：{', '.join(missing)}")
    camera = config["camera"]
    minimum = float(camera["min_depth_mm"])
    maximum = float(camera["max_depth_mm"])
    if minimum <= 0 or maximum <= minimum:
        raise ValueError("camera深度范围无效：必须满足0 < min_depth_mm < max_depth_mm")
    roi = config["table"]["roi_normalized"]
    if not isinstance(roi, list) or len(roi) != 4:
        raise ValueError("table.roi_normalized必须包含四个数字")
    x0, y0, x1, y1 = map(float, roi)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("table.roi_normalized必须满足0≤x0<x1≤1且0≤y0<y1≤1")
