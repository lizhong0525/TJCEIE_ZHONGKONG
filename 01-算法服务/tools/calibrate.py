"""``tools/calibrate.py`` —— 交互式把现场标定数值写入 ``config/site.yaml``。

设计目标：

* 不引入额外依赖（只用 PyYAML + stdlib）。
* 一次性把 spec 列出的所有数值（相机内参/畸变、手眼、台面、面板灯与开关、
  形状与槽位、数字赛具）收集起来，统一落盘。
* 已存在的 YAML 字段会被保留为默认值，回车跳过即不修改。

执行：``python -m tools.calibrate``，或在 ``tools/`` 下 ``python calibrate.py``。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

# 确保 ``from algorithm_service.config import write`` 可用，无论从哪跑
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_service.config import PLACEHOLDER, write  # noqa: E402


def _ask(prompt: str, caster: Callable[[str], Any], default: Any) -> Any:
    """读取一行输入；空行返回 ``default``。"""

    hint = f" [{default}]" if default not in (None, PLACEHOLDER, "") else ""
    raw = input(f"{prompt}{hint}: ").strip()
    if raw == "":
        return default
    try:
        return caster(raw)
    except (ValueError, TypeError) as e:
        print(f"  ! 输入无效（{e}），保留原值 {default}")
        return default


def _ask_str(prompt: str, default: str) -> str:
    return _ask(prompt, str, default)


def _ask_float(prompt: str, default: float) -> float:
    return _ask(prompt, float, default)


def _ask_int(prompt: str, default: int) -> int:
    return _ask(prompt, int, default)


def _ask_vec3(prefix: str, default: dict[str, Any]) -> dict[str, Any]:
    print(f"  {prefix}  (回车跳过沿用旧值)")
    return {
        "x": _ask_float("    x", default.get("x", PLACEHOLDER)),
        "y": _ask_float("    y", default.get("y", PLACEHOLDER)),
        "z": _ask_float("    z", default.get("z", PLACEHOLDER)),
    }


def _ensure_section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in raw or not isinstance(raw[key], dict):
        raw[key] = {}
    return raw[key]


def calibrate_site(config_path: Path) -> None:
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    print(f"== 写入 {config_path} ==")
    print("直接回车 = 沿用括号内旧值；输入 0 不会被误认成占位。\n")

    # 1. 相机
    cam = _ensure_section(raw, "camera")
    print("[1/7] 相机内参")
    cam["fx"] = _ask_float("fx", cam.get("fx", PLACEHOLDER))
    cam["fy"] = _ask_float("fy", cam.get("fy", PLACEHOLDER))
    cam["cx"] = _ask_float("cx", cam.get("cx", PLACEHOLDER))
    cam["cy"] = _ask_float("cy", cam.get("cy", PLACEHOLDER))

    dist = _ensure_section(raw, "distortion")
    print("\n[2/7] 畸变系数")
    dist["k1"] = _ask_float("k1", dist.get("k1", 0.0))
    dist["k2"] = _ask_float("k2", dist.get("k2", 0.0))
    dist["p1"] = _ask_float("p1", dist.get("p1", 0.0))
    dist["p2"] = _ask_float("p2", dist.get("p2", 0.0))

    # 2. 手眼 4x4
    he = _ensure_section(raw, "hand_eye")
    rows = he.get("rows")
    if not (isinstance(rows, list) and len(rows) == 4):
        rows = [[PLACEHOLDER] * 4 for _ in range(4)]
    print("\n[3/7] 手眼矩阵（基座→相机，4x4，每行 4 个空格分隔）")
    new_rows: list[list[float]] = []
    for i in range(4):
        default_row = [str(c) for c in rows[i]]
        line = _ask_str(f"  row {i}  (old={default_row})", " ".join(default_row))
        parts = line.replace(",", " ").split()
        while len(parts) < 4:
            parts.append(PLACEHOLDER)
        new_rows.append([float(p) if p != PLACEHOLDER else PLACEHOLDER for p in parts[:4]])
    he["rows"] = new_rows

    # 3. 安全区
    sb = _ensure_section(raw, "safe_box")
    print("\n[4/7] 安全区 (m)")
    for axis in ("x", "y", "z"):
        sb[f"{axis}_min"] = _ask_float(f"  {axis}_min", sb.get(f"{axis}_min", PLACEHOLDER))
        sb[f"{axis}_max"] = _ask_float(f"  {axis}_max", sb.get(f"{axis}_max", PLACEHOLDER))

    # 4. 抓取抬升
    pick = _ensure_section(raw, "pick")
    print("\n[5/7] 抓取抬升高度 (m)")
    pick["approach_height"] = _ask_float("  approach_height", pick.get("approach_height", PLACEHOLDER))

    # 5. 控制面板（赛题 1：拍照位 + 3 灯 + 3 开关）
    panel = _ensure_section(raw, "panel")
    print("\n[6/7] 控制面板（赛题 1：3 个指示灯 + 下方 2 按钮 + 1 拨动开关）")
    panel.setdefault("photo_pose", {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
    panel["photo_pose"] = _ask_vec3("拍照位（末端位置, m）", panel["photo_pose"])

    default_lamps = [
        {"name": "lamp_red", "color": "red", "switch": "btn_red"},
        {"name": "lamp_yellow", "color": "yellow", "switch": "btn_yellow"},
        {"name": "lamp_green", "color": "green", "switch": "sw_toggle"},
    ]
    existing_lamps = panel.get("lamps") or []
    while len(existing_lamps) < 3:
        idx = len(existing_lamps)
        preset = default_lamps[idx] if idx < len(default_lamps) else {
            "name": f"lamp_{idx+1}", "color": "red", "switch": f"sw_{idx+1}",
        }
        existing_lamps.append({**preset, "roi": [PLACEHOLDER] * 4})
    print("  3 个指示灯（roi = 拍照位下的像素区域 [u0, v0, u1, v1]）：")
    new_lamps: list[dict[str, Any]] = []
    for i, lamp in enumerate(existing_lamps[:3]):
        print(f"  -- Lamp #{i+1} --")
        name = _ask_str("    name", lamp.get("name", f"lamp_{i+1}"))
        color = _ask_str("    color (red/yellow/green)", lamp.get("color", "red"))
        switch = _ask_str("    对应开关 name", lamp.get("switch", ""))
        roi_old = lamp.get("roi") if isinstance(lamp.get("roi"), list) else [PLACEHOLDER] * 4
        roi: list[Any] = []
        for j, axis in enumerate(("u0", "v0", "u1", "v1")):
            roi.append(_ask_int(f"    roi.{axis}", roi_old[j] if j < len(roi_old) else PLACEHOLDER))
        new_lamps.append({"name": name, "color": color, "switch": switch, "roi": roi})
    panel["lamps"] = new_lamps

    default_switches = [
        {"name": "btn_red", "kind": "push"},
        {"name": "btn_yellow", "kind": "push"},
        {"name": "sw_toggle", "kind": "toggle"},
    ]
    existing_switches = panel.get("switches") or []
    while len(existing_switches) < 3:
        idx = len(existing_switches)
        base = default_switches[idx] if idx < len(default_switches) else {
            "name": f"sw_{idx+1}", "kind": "push",
        }
        existing_switches.append({
            **base,
            "pos": {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER},
            "act_dir": {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER},
        })
    print("  3 个开关（act_dir 单位向量：push=压入面板方向 / toggle=拨动方向）：")
    new_switches: list[dict[str, Any]] = []
    for i, s in enumerate(existing_switches[:3]):
        print(f"  -- Switch #{i+1} --")
        name = _ask_str("    name", s.get("name", f"sw_{i+1}"))
        kind = _ask_str("    kind (push/toggle)", s.get("kind", "push"))
        pos = _ask_vec3("    pos 接触点 (m)", s.get("pos") or {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
        act_dir = _ask_vec3("    act_dir 单位向量", s.get("act_dir") or {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
        travel_default = 0.02 if kind == "toggle" else 0.005
        travel = _ask_float("    travel 行程 (m)", s.get("travel", travel_default))
        standoff = _ask_float("    standoff 退让 (m)", s.get("standoff", 0.06))
        new_switches.append({
            "name": name, "kind": kind, "pos": pos, "act_dir": act_dir,
            "travel": travel, "standoff": standoff,
        })
    panel["switches"] = new_switches
    # 旧版字段（6 按钮模型）废弃，重跑标定时顺手清掉
    panel.pop("center", None)
    panel.pop("buttons", None)

    # 6. 数字长方体
    db = _ensure_section(raw, "digit_blocks")
    print("\n[7a/7] 数字长方体")
    db["expected_count"] = _ask_int("  expected_count", db.get("expected_count", 0) or 0)
    db["placement_order_target"] = _ask_str(
        "  placement_order_target (ascending/descending)", db.get("placement_order_target", "ascending")
    )
    db.setdefault("staging_area", {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
    db.setdefault("placement_area", {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
    db["staging_area"] = _ask_vec3("  staging_area", db["staging_area"])
    db["placement_area"] = _ask_vec3("  placement_area", db["placement_area"])
    slots_in = db.get("slots") or []
    if not slots_in:
        slots_in = [{"name": f"slot_{i+1}", "pos": {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER}} for i in range(4)]
    new_slots: list[dict[str, Any]] = []
    for i, s in enumerate(slots_in):
        pos = _ask_vec3(f"  slot[{i}] (name={s.get('name','slot')})", s.get("pos") or {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
        new_slots.append({"name": s.get("name", f"slot_{i+1}"), "pos": pos})
    db["slots"] = new_slots

    # 7. 形状
    sh = _ensure_section(raw, "shapes")
    print("\n[7b/7] 形状与槽位")
    sh.setdefault("staging_area", {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
    sh["staging_area"] = _ask_vec3("  staging_area", sh["staging_area"])
    kinds_in = sh.get("kinds") or []
    if not kinds_in:
        kinds_in = [
            {"name": "round", "slots": [{"name": f"round_{i+1}", "pos": {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER}} for i in range(2)]},
            {"name": "square", "slots": [{"name": f"square_{i+1}", "pos": {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER}} for i in range(2)]},
            {"name": "irregular", "slots": [{"name": f"irregular_{i+1}", "pos": {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER}} for i in range(1)]},
        ]
    new_kinds: list[dict[str, Any]] = []
    for k in kinds_in:
        name = _ask_str(f"  shape name (old={k.get('name','')})", k.get("name", ""))
        slots_in_k = k.get("slots") or []
        new_k_slots: list[dict[str, Any]] = []
        for i, s in enumerate(slots_in_k):
            pos = _ask_vec3(f"    slot[{i}]", s.get("pos") or {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER})
            new_k_slots.append({"name": s.get("name", f"{name}_{i+1}"), "pos": pos})
        new_kinds.append({"name": name, "slots": new_k_slots})
    sh["kinds"] = new_kinds

    write(config_path, raw)
    print(f"\n[OK] 已写入 {config_path}")


def main() -> int:
    p = argparse.ArgumentParser(description="交互式写入 site.yaml 标定数值")
    p.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "site.yaml",
        help="site.yaml 路径（默认：项目 config/site.yaml）",
    )
    args = p.parse_args()
    calibrate_site(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
