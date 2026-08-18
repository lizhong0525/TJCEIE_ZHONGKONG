"""赛题 2 —— 数字长方体：识别→排序→按序 pick & place。

* 视觉识别委托给 ``task2_vision.recognize_digits``（返回
  ``[(block_id, digit, pick_pose)]``）。
* 排序按 ``cfg.digit_blocks.placement_order_target``（ascending/descending）。
* 槽位顺序取 ``cfg.digit_blocks.slots``。
* 真实坐标由 ``_coords.pixel_to_base_pose``（``t_base_end @ t_end_camera`` 链）计算；
  这里接受 ``vision_capture`` 钩子直接返回帧，便于 mock 与单元测试。
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
    """``digit_blocks.expected_count``；占位/非法返回 0（由 run() 拒绝执行）。"""

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
        if expected <= 0:
            # A 级防线：expected_count 占位/为 0 时数量校验形同虚设（识别 3 个也照放）
            raise PickError(
                "digit_blocks.expected_count 未标定或 <= 0（数量校验必须生效，请按赛题实际块数配置）"
            )
        raw = recognize_digits(color, depth, cfg, frame.get("t_base_end"),
                               allow_staging=bool(frame.get("allow_staging")))
        if (not raw) or len(raw) != expected:
            # 一次重拍重识别（6.6：没把握就重拍，绝不能猜；彩色/深度必须同一帧）
            frame2 = vision_capture() or {}
            retry = recognize_digits(frame2.get("color"), frame2.get("depth"), cfg,
                                     frame2.get("t_base_end"),
                                     allow_staging=bool(frame2.get("allow_staging")))
            # 挑更可信的一次：恰好识别够 expected 的优先，都没有就选数量更接近 expected 的
            # （"更多"≠"更对"：第一次误检 5 个、重拍正确 4 个时不能选错的）
            if len(retry) == expected:
                raw = retry
            elif abs(len(retry) - expected) < abs(len(raw) - expected):
                raw = retry
            if len(raw) != expected:
                raise PickError(
                    f"digit recognition failed: got {len(raw)} expected {expected}（已重拍一次）"
                )

        # 排序（白名单校验：拼错如 "desending" 归正 ascending 并告警，绝不静默反序）
        order = (cfg.digit_blocks.placement_order_target or "ascending").lower()
        if order not in ("ascending", "descending"):
            LOG.warning(
                "placement_order_target=%r 不是 ascending/descending（拼写错误？），按 ascending 处理",
                cfg.digit_blocks.placement_order_target,
            )
            order = "ascending"
        reverse = order == "descending"
        # 第二键 pick.x：同数字（识别异常时）也有确定性顺序
        raw_sorted = sorted(raw, key=lambda b: (b.digit, b.pick.x), reverse=reverse)

        # 槽位
        slots = cfg.digit_blocks.slots
        if not slots:
            raise PickError("digit_blocks.slots 未配置")
        if len(raw_sorted) > len(slots):
            raise PickError(
                f"识别到 {len(raw_sorted)} 个长方体，槽位仅有 {len(slots)} 个"
            )
        if len(slots) != expected:
            # 交叉告警：expected_count 与槽位数对不上多半是标定填错，不拦但留个记录
            LOG.warning(
                "expected_count=%d 与 slots 数量 %d 不一致（标定填错？），请核对 site.yaml",
                expected, len(slots),
            )

        poses = hand_pose_table(cfg)
        retries = max(0, int(cfg.digit_blocks.grasp_retries))
        placed: list[DigitBlock] = []
        with hand.errors_watch() as watcher:
            for blk, slot in zip(raw_sorted, slots):
                if watcher.first_error:
                    # 8.4：手报错立即中止（走外层撤回）
                    raise PickError(f"灵巧手错误码非 0: {watcher.first_error}（按 8.4 停手撤臂）")
                target_slot = pose_from_vec3(slot.pos, f"槽位 {slot.name}")
                # 抓起失败可重试 N 次（6.7）；放置失败不重试（块可能已在手/在槽，重来更危险）
                last_err: Exception | None = None
                for attempt in range(retries + 1):
                    try:
                        planner_pick(arm, hand, cfg, blk.pick, "grasp_digit", poses)
                        last_err = None
                        break
                    except (ArmError, HandError, PickError) as e:
                        # planner 已把 ArmError/HandError 包成 PickError，必须一并捕获
                        last_err = e
                        LOG.warning(
                            "块 %s(数字 %d) 第 %d/%d 次抓取失败: %s",
                            blk.block_id, blk.digit, attempt + 1, retries + 1, e,
                        )
                if last_err is not None:
                    raise PickError(
                        f"块 {blk.block_id}(数字 {blk.digit}) 抓取 {retries + 1} 次均失败: {last_err}"
                    ) from last_err
                try:
                    planner_place(arm, hand, cfg, target_slot, poses, open_after=True)
                except (ArmError, HandError, PickError) as e:
                    raise PickError(f"块 {blk.block_id}(数字 {blk.digit}) 放置失败: {e}") from e
                placed.append(blk)
        if watcher.first_error:
            raise PickError(f"灵巧手错误码非 0: {watcher.first_error}（按 8.4 停手撤臂）")
    except Exception:
        retreat_best_effort(arm, cfg)
        raise

    safe_home(arm, cfg, vel=cfg.service.final_vel)
    return placed
