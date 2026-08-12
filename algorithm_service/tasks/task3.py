"""赛题 3 —— 多面体形状分类入槽。

* 形状分类由 ``task3_vision.classify_shapes`` 给出（圆形/方形/异形）。
* 槽位由 ``cfg.shapes.kinds`` 按 ``name`` 查找；不强制顺序。
* 跳过未登记类别并在 message 中记录。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..config import SiteConfig, is_placeholder
from ..hardware import ArmClient, ArmError, HandClient, HandError
from ..planner import (
    PickError,
    Pose,
    hand_pose_table,
    pick as planner_pick,
    place as planner_place,
    safe_home,
)
from .task3_vision import classify_shapes

LOG = logging.getLogger(__name__)


@dataclass
class ShapeResult:
    placed: list[tuple[str, str]]     # [(block_id, shape_name)]
    skipped: list[tuple[str, str]]    # 未登记类别


def run(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    vision_capture: Callable[[], dict[str, Any]] | None = None,
) -> ShapeResult:
    if not arm.healthy():
        raise PickError("机械臂状态不健康")
    if not arm.enabled():
        arm.enable()
    safe_home(arm, cfg)

    if vision_capture is None:
        raise PickError("vision_capture 未注入")
    frame = vision_capture()
    color = frame.get("color")
    depth = frame.get("depth")
    if color is None:
        raise PickError("camera not ready")

    raw = classify_shapes(color, depth, cfg)
    if not raw:
        raise PickError("shape recognition failed: got 0")

    poses = hand_pose_table(cfg)
    placed: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    used_slots: dict[str, int] = {}

    with hand.errors_watch():
        for blk_id, shape, pick_pose in raw:
            if is_placeholder(pick_pose.x):
                raise PickError(f"块 {blk_id} 坐标未标定")
            slots = cfg.shapes.slots_for(shape)
            if not slots:
                skipped.append((blk_id, shape))
                continue
            used = used_slots.get(shape, 0)
            if used >= len(slots):
                skipped.append((blk_id, shape))
                continue
            slot = slots[used]
            if is_placeholder(slot.pos.x):
                raise PickError(f"形状 {shape} 槽位 {slot.name} 未标定")
            try:
                planner_pick(arm, hand, cfg, pick_pose, "grasp_shape", poses)
                target = Pose(float(slot.pos.x), float(slot.pos.y), float(slot.pos.z))
                planner_place(arm, hand, cfg, target, poses, open_after=True)
                used_slots[shape] = used + 1
                placed.append((blk_id, shape))
            except (ArmError, HandError) as e:
                raise PickError(f"处理 {blk_id}({shape}) 失败: {e}") from e

    safe_home(arm, cfg, vel=cfg.service.final_vel)
    if skipped:
        LOG.info("task3 skipped (unregistered shape or full slots): %s", skipped)
    return ShapeResult(placed=placed, skipped=skipped)
