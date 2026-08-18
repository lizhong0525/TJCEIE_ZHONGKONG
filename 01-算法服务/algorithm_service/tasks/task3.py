"""赛题 3 —— 多面体形状分类入槽。

* 形状分类由 ``task3_vision.classify_shapes`` 给出（7.2 四分类：triangular_prism/
  hexagonal_prism/rectangular_prism/cylinder）。
* 槽位由 ``cfg.shapes.kinds`` 按 ``name`` 查找；不强制顺序。
* 跳过未登记类别并在 message 中记录。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..config import SiteConfig
from ..hardware import ArmClient, ArmError, HandClient, HandError
from ..planner import (
    PickError,
    hand_pose_table,
    pick as planner_pick,
    place as planner_place,
    pose_from_vec3,
    retreat_best_effort,
    safe_home,
)
from .task3_vision import classify_shapes

LOG = logging.getLogger(__name__)


@dataclass
class ShapeResult:
    placed: list[tuple[str, str]]     # [(block_id, shape_name)]
    skipped: list[tuple[str, str]]    # 未登记类别
    failed: list[tuple[str, str]]     # 抓取/放置失败（7.7：不中止，继续剩余块）


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

    try:
        frame = vision_capture()
        color = frame.get("color")
        depth = frame.get("depth")
        if color is None:
            raise PickError("camera not ready")

        # 无深度图时只有显式注入的自检 mock（frame["allow_staging"]）才允许回退
        # staging 坐标；生产链路无深度图会在 classify_shapes 里抛 PickError
        allow_staging = bool(frame.get("allow_staging"))
        raw = classify_shapes(color, depth, cfg, frame.get("t_base_end"),
                              allow_staging=allow_staging)
        if not raw:
            # 与 task2 对齐：识别 0 个时重拍一次再判（没把握就重拍，绝不能猜）
            frame2 = vision_capture() or {}
            raw = classify_shapes(
                frame2.get("color"), frame2.get("depth"), cfg,
                frame2.get("t_base_end"),
                allow_staging=bool(frame2.get("allow_staging")),
            )
        if not raw:
            raise PickError("shape recognition failed: got 0（已重拍一次）")

        poses = hand_pose_table(cfg)
        placed: list[tuple[str, str]] = []
        skipped: list[tuple[str, str]] = []
        failed: list[tuple[str, str]] = []
        used_slots: dict[str, int] = {}

        with hand.errors_watch() as watcher:
            for blk in raw:
                if watcher.first_error:
                    # 8.4：手报错不停留在原地继续抓，直接中止（走外层撤回）
                    raise PickError(f"灵巧手错误码非 0: {watcher.first_error}（按 8.4 停手撤臂）")
                blk_id, shape, pick_pose = blk.block_id, blk.shape, blk.pick
                slots = cfg.shapes.slots_for(shape)
                if not slots:
                    skipped.append((blk_id, shape))
                    continue
                used = used_slots.get(shape, 0)
                if used >= len(slots):
                    skipped.append((blk_id, shape))
                    continue
                slot = slots[used]
                target = pose_from_vec3(slot.pos, f"形状 {shape} 槽位 {slot.name}")
                try:
                    planner_pick(arm, hand, cfg, pick_pose, "grasp_shape", poses)
                    planner_place(arm, hand, cfg, target, poses, open_after=True)
                except (ArmError, HandError, PickError) as e:
                    # 7.7：单块失败/掉落不中止，记录后继续分拣剩余块
                    # （planner 已把 ArmError/HandError 包成 PickError，必须一并捕获）
                    LOG.warning("块 %s(%s) 处理失败，继续剩余块: %s", blk_id, shape, e)
                    failed.append((blk_id, shape))
                    continue
                used_slots[shape] = used + 1
                placed.append((blk_id, shape))
        if watcher.first_error:
            raise PickError(f"灵巧手错误码非 0: {watcher.first_error}（按 8.4 停手撤臂）")

        if not placed:
            # A 级防线：全跳过（形状名与 shapes.kinds 对不上）或全失败都不得报 success——
            # 竞赛软件只看 success，一个没放绝不能返回 true
            raise PickError(
                f"一个几何体都没放入槽（识别 {len(raw)} 个：跳过 {len(skipped)}、失败 {len(failed)}）。"
                f"全跳过多半是识别类别名与 site.yaml 的 shapes.kinds 名称对不上；全失败请检查硬件"
            )
    except Exception:
        retreat_best_effort(arm, cfg)
        raise

    safe_home(arm, cfg, vel=cfg.service.final_vel)
    if skipped:
        LOG.info("task3 skipped (unregistered shape or full slots): %s", skipped)
    if failed:
        LOG.warning("task3 failed blocks (7.7 继续分拣后仍未完成): %s", failed)
    return ShapeResult(placed=placed, skipped=skipped, failed=failed)
