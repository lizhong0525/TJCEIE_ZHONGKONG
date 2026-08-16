"""赛题 2 —— 数字长方体：识别→排序→按序 pick & place。

* 视觉识别委托给 ``task2_vision.recognize_digits``（返回
  ``[(block_id, digit, pick_pose)]``）。
* 排序按 ``cfg.digit_blocks.placement_order_target``（ascending/descending）。
* 槽位顺序取 ``cfg.digit_blocks.slots``。
* 真实坐标由 ``Vision.pixel_to_base`` 计算；这里接受 ``vision_capture`` 钩子直接返回
  基座系坐标，便于 mock 与单元测试。
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
    pose_from_vec3,
    retreat_best_effort,
    safe_home,
)
from .task2_vision import recognize_digits

LOG = logging.getLogger(__name__)


@dataclass
class DigitBlock:
    block_id: int
    digit: int
    pick: Pose


def _expected_count(cfg: SiteConfig) -> int:
    if is_placeholder(cfg.digit_blocks.expected_count):
        return 0
    try:
        return int(cfg.digit_blocks.expected_count)
    except (TypeError, ValueError):
        return 0


def run(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    vision_capture: Callable[[], dict[str, Any]] | None = None,
) -> list[DigitBlock]:
    if not arm.healthy():
        raise PickError("机械臂状态不健康")
    if not arm.enabled():
        arm.enable()
    safe_home(arm, cfg)

    if vision_capture is None:
        raise PickError("vision_capture 未注入")

    try:
        frame = vision_capture()
        color = frame.get("color")
        depth = frame.get("depth")
        if color is None:
            raise PickError("camera not ready")

        expected = _expected_count(cfg)
        raw = recognize_digits(color, depth, cfg)
        if (not raw) or (expected and len(raw) != expected):
            # 一次重试
            retry = recognize_digits(
                (vision_capture() or {}).get("color"),
                (vision_capture() or {}).get("depth"),
                cfg,
            )
            if expected and len(retry) == expected:
                raw = retry
            elif not raw:
                raise PickError(f"digit recognition failed: got 0 expected {expected}")
            else:
                raise PickError(
                    f"digit recognition failed: got {len(raw)} expected {expected}"
                )

        # 排序
        order = (cfg.digit_blocks.placement_order_target or "ascending").lower()
        reverse = order == "descending"
        raw_sorted = sorted(raw, key=lambda b: b.digit, reverse=reverse)

        # 槽位
        slots = cfg.digit_blocks.slots
        if not slots:
            raise PickError("digit_blocks.slots 未配置")
        if len(raw_sorted) > len(slots):
            raise PickError(
                f"识别到 {len(raw_sorted)} 个长方体，槽位仅有 {len(slots)} 个"
            )

        poses = hand_pose_table(cfg)
        placed: list[DigitBlock] = []
        with hand.errors_watch():
            for blk, slot in zip(raw_sorted, slots):
                try:
                    planner_pick(arm, hand, cfg, blk.pick, "grasp_digit", poses)
                    target_slot = pose_from_vec3(slot.pos, f"槽位 {slot.name}")
                    planner_place(arm, hand, cfg, target_slot, poses, open_after=True)
                    placed.append(blk)
                except (ArmError, HandError) as e:
                    raise PickError(f"处理 {blk} 失败: {e}") from e
    except Exception:
        retreat_best_effort(arm, cfg)
        raise

    safe_home(arm, cfg, vel=cfg.service.final_vel)
    return placed
