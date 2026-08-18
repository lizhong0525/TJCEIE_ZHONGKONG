from __future__ import annotations

import logging
from typing import Any

from .config import RuntimeConfig
from .models import BlockObservation, MotionError, Pose6D, Task2Error, Task2Result

LOG = logging.getLogger(__name__)


class Task2Controller:
    """任务二唯一业务入口；任何部分失败都返回 success=false。"""

    def __init__(self, config: RuntimeConfig, arm: Any, hand: Any, vision: Any):
        self.config = config
        self.arm = arm
        self.hand = hand
        self.vision = vision

    def _retreat_best_effort(self) -> None:
        try:
            self.arm.cancel()
        except Exception:
            pass
        if not bool(self.config.task.get("retreat_on_failure", False)):
            LOG.error("异常后保持当前位置；请由现场人员确认状态后人工处理")
            return
        try:
            speed = float(self.config.task.get("final_speed", 0.04))
            self.arm.move_linear(self.config.safe_pose, speed=speed, label="失败撤回安全位")
        except Exception as exc:
            LOG.error("失败后无法撤回安全位: %s", exc)

    def _pick(self, block: BlockObservation) -> None:
        task = self.config.task
        approach = block.pick_pose.raised(float(task.get("approach_height_m", 0.06)))
        self.hand.open()
        self.arm.move_linear(
            approach,
            speed=float(task.get("travel_speed", 0.10)),
            label=f"数字{block.digit}抓取接近点",
        )
        self.arm.move_linear(
            block.pick_pose,
            speed=float(task.get("final_speed", 0.04)),
            label=f"数字{block.digit}抓取点",
        )
        self.hand.grasp_block()
        self.arm.move_linear(
            approach,
            speed=float(task.get("final_speed", 0.04)),
            label=f"数字{block.digit}抓取撤回点",
        )

    def _place(self, block: BlockObservation) -> None:
        task = self.config.task
        destination = self.config.destination_slots[block.digit]
        target = destination.pose
        # 赛题要求放置姿态与槽内姿态一致：目标位置来自右侧台面标定，
        # 末端姿态沿用抓取时姿态，避免只保留yaw却改变roll/pitch。
        preserve = bool(task.get("preserve_source_orientation", task.get("preserve_source_yaw", True)))
        if preserve:
            target = Pose6D(
                target.x, target.y, target.z,
                block.pick_pose.roll, block.pick_pose.pitch, block.source_yaw,
            )
        approach = target.raised(float(task.get("approach_height_m", 0.06)))
        self.arm.move_linear(
            approach,
            speed=float(task.get("travel_speed", 0.10)),
            label=f"数字{block.digit}放置接近点",
        )
        self.arm.move_linear(
            target,
            speed=float(task.get("final_speed", 0.04)),
            label=f"数字{block.digit}放置点",
        )
        self.hand.open()
        self.arm.move_linear(
            approach,
            speed=float(task.get("final_speed", 0.04)),
            label=f"数字{block.digit}放置撤回点",
        )

    def run(self) -> Task2Result:
        if not self.config.allow_motion:
            return Task2Result(False, "service.allow_motion=false；完成现场标定和低速验证后才能启用真机运动")
        completed: list[int] = []
        source_by_id = {slot.slot_id: slot for slot in self.config.source_slots}
        try:
            if not self.arm.healthy():
                raise MotionError("机械臂电机状态不健康")
            self.arm.enable()
            self.hand.ensure_ready()

            self.arm.move_linear(
                self.config.safe_pose,
                speed=float(self.config.task.get("travel_speed", 0.10)),
                label="任务开始安全位",
            )
            self.arm.move_linear(
                self.config.photo_pose,
                speed=float(self.config.task.get("travel_speed", 0.10)),
                label="任务二拍照位",
            )

            observations = self.vision.acquire_complete_mapping(self.arm.current_pose)
            if [item.digit for item in observations] != [1, 2, 3, 4]:
                raise Task2Error("内部保护：识别结果不是严格的1→2→3→4")

            LOG.info(
                "数字到真实物理槽映射: %s",
                {item.digit: item.source_slot_id for item in observations},
            )
            for block in observations:
                if block.source_slot_id not in source_by_id:
                    raise Task2Error(f"识别结果引用未知源槽 {block.source_slot_id}")
                self.hand.ensure_no_errors()
                self._pick(block)
                self._place(block)

                verify = self.config.task.get("verification") or {}
                if bool(verify.get("enabled", True)):
                    self.arm.move_linear(
                        self.config.photo_pose,
                        speed=float(self.config.task.get("travel_speed", 0.10)),
                        label=f"数字{block.digit}放置后验证拍照位",
                    )
                    self.vision.verify_transfer(
                        source_by_id[block.source_slot_id],
                        self.config.destination_slots[block.digit],
                        block.digit,
                    )
                completed.append(block.digit)

            if completed != [1, 2, 3, 4]:
                raise Task2Error(f"只完成 {completed}，任务二不得返回成功")
            self.arm.move_linear(
                self.config.safe_pose,
                speed=float(self.config.task.get("travel_speed", 0.10)),
                label="任务结束安全位",
            )
            mapping = {item.digit: item.source_slot_id for item in observations}
            return Task2Result(
                True,
                f"任务二完成：严格按1→2→3→4转运，物理槽映射={mapping}",
                tuple(completed),
            )
        except Exception as exc:
            self._retreat_best_effort()
            return Task2Result(
                False,
                f"任务二失败（已停止后续动作）: {type(exc).__name__}: {str(exc)[:240]}",
                tuple(completed),
            )
