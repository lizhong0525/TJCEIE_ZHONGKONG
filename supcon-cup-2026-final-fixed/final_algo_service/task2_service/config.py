from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ConfigError, Pose6D


PLACEHOLDER = "__现场标定后填入__"


def _has_placeholder(value: Any) -> bool:
    if value == PLACEHOLDER:
        return True
    if isinstance(value, dict):
        return any(_has_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_placeholder(v) for v in value)
    return False


def _roi(value: Any, label: str) -> tuple[float, float, float, float]:
    try:
        vals = tuple(float(x) for x in value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} 必须是4个0~1之间的比例") from exc
    if len(vals) != 4 or not (0 <= vals[0] < vals[2] <= 1 and 0 <= vals[1] < vals[3] <= 1):
        raise ConfigError(f"{label} 非法，应为 [left,top,right,bottom] 且范围0~1")
    return vals  # type: ignore[return-value]


@dataclass(frozen=True)
class SourceSlot:
    slot_id: str
    roi: tuple[float, float, float, float]
    pick_pose: Pose6D
    empty_depth_mm: float | None


@dataclass(frozen=True)
class DestinationSlot:
    digit: int
    pose: Pose6D
    roi: tuple[float, float, float, float] | None
    empty_depth_mm: float | None


@dataclass(frozen=True)
class RuntimeConfig:
    raw: dict[str, Any]
    source_slots: tuple[SourceSlot, ...]
    destination_slots: dict[int, DestinationSlot]
    photo_pose: Pose6D
    safe_pose: Pose6D

    @property
    def allow_motion(self) -> bool:
        return bool(self.raw["service"].get("allow_motion", False))

    @property
    def task(self) -> dict[str, Any]:
        return self.raw["task2"]


def load_config(path: str | Path) -> RuntimeConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"配置文件不存在: {p}")
    with p.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)

    for section in ("service", "arm", "hand", "camera", "calibration", "ocr", "task2"):
        if section not in raw or not isinstance(raw[section], dict):
            raise ConfigError(f"缺少配置段 {section}")

    task = raw["task2"]
    if _has_placeholder(task):
        raise ConfigError("task2 中仍有 __现场标定后填入__，禁止控制真机")
    if _has_placeholder(raw["arm"].get("safe_box")):
        raise ConfigError("arm.safe_box 未标定，禁止控制真机")
    if _has_placeholder(raw["arm"].get("safe_pose")):
        raise ConfigError("arm.safe_pose 未标定，禁止控制真机")
    if _has_placeholder(raw["hand"].get("poses")):
        raise ConfigError("hand.poses 中仍有现场占位参数，禁止控制真机")
    if bool(task.get("use_rgbd_refinement", False)) and _has_placeholder(raw["calibration"]):
        raise ConfigError("已启用RGB-D精修，但手眼标定仍是占位")

    safe_box = raw["arm"]["safe_box"]
    try:
        for axis in ("x", "y", "z"):
            if float(safe_box[f"{axis}_min"]) >= float(safe_box[f"{axis}_max"]):
                raise ConfigError(f"arm.safe_box.{axis}_min 必须小于 {axis}_max")
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("arm.safe_box 必须包含数值 x/y/z 的 min 和 max") from exc

    if bool(task.get("use_rgbd_refinement", False)):
        offset = task.get("rgbd_pick_offset_xyz_m")
        try:
            values = [float(v) for v in offset]
        except (TypeError, ValueError) as exc:
            raise ConfigError("rgbd_pick_offset_xyz_m 必须是3个数值") from exc
        if len(values) != 3:
            raise ConfigError("rgbd_pick_offset_xyz_m 必须是3个数值")

    source: list[SourceSlot] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(task.get("source_slots") or []):
        label = f"task2.source_slots[{index}]"
        slot_id = str(item.get("id", "")).strip()
        if not slot_id or slot_id in seen_ids:
            raise ConfigError(f"{label}.id 为空或重复")
        seen_ids.add(slot_id)
        empty = item.get("empty_depth_mm")
        source.append(SourceSlot(
            slot_id=slot_id,
            roi=_roi(item.get("roi"), f"{label}.roi"),
            pick_pose=Pose6D.from_dict(item.get("pick_pose") or {}, f"{label}.pick_pose"),
            empty_depth_mm=None if empty is None else float(empty),
        ))
    if len(source) != 4:
        raise ConfigError(f"必须配置4个真实物理源槽位，当前 {len(source)} 个")

    destinations: dict[int, DestinationSlot] = {}
    for index, item in enumerate(task.get("destination_slots") or []):
        label = f"task2.destination_slots[{index}]"
        try:
            digit = int(item["digit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"{label}.digit 非法") from exc
        if digit not in (1, 2, 3, 4) or digit in destinations:
            raise ConfigError(f"{label}.digit 必须是唯一的1~4")
        roi = None if item.get("roi") is None else _roi(item["roi"], f"{label}.roi")
        empty = item.get("empty_depth_mm")
        destinations[digit] = DestinationSlot(
            digit=digit,
            pose=Pose6D.from_dict(item.get("pose") or {}, f"{label}.pose"),
            roi=roi,
            empty_depth_mm=None if empty is None else float(empty),
        )
    if set(destinations) != {1, 2, 3, 4}:
        raise ConfigError("必须为数字1、2、3、4配置四个不同放置点")
    xyz = {(round(v.pose.x, 6), round(v.pose.y, 6), round(v.pose.z, 6)) for v in destinations.values()}
    if len(xyz) != 4:
        raise ConfigError("四个 destination_slots 不能使用相同放置坐标")

    for name in ("open", "grasp_block"):
        values = (raw["hand"].get("poses") or {}).get(name)
        if not isinstance(values, list) or len(values) != 10:
            raise ConfigError(f"hand.poses.{name} 必须是10个0~1数值")
        try:
            numbers = [float(v) for v in values]
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"hand.poses.{name} 必须是10个0~1数值") from exc
        if any(v < 0 or v > 1 for v in numbers):
            raise ConfigError(f"hand.poses.{name} 必须是10个0~1数值")

    verify = task.get("verification") or {}
    if bool(verify.get("enabled", True)):
        if any(s.empty_depth_mm is None for s in source):
            raise ConfigError("启用动作后验证时，四个源槽必须填写 empty_depth_mm")
        if any(d.roi is None or d.empty_depth_mm is None for d in destinations.values()):
            raise ConfigError("启用动作后验证时，四个放置点必须填写 roi 和 empty_depth_mm")

    return RuntimeConfig(
        raw=raw,
        source_slots=tuple(source),
        destination_slots=destinations,
        photo_pose=Pose6D.from_dict(task.get("photo_pose") or {}, "task2.photo_pose"),
        safe_pose=Pose6D.from_dict(raw["arm"].get("safe_pose") or {}, "arm.safe_pose"),
    )
