from __future__ import annotations

from dataclasses import replace
import unittest

from task2_service.config import DestinationSlot, RuntimeConfig, SourceSlot
from task2_service.controller import Task2Controller
from task2_service.models import BlockObservation, MotionError, Pose6D, VisionError


def pose(x: float, y: float, z: float, yaw: float = 0.0) -> Pose6D:
    return Pose6D(x, y, z, 0.0, 0.0, yaw)


def runtime(verification: bool = False) -> RuntimeConfig:
    sources = tuple(
        SourceSlot(
            slot_id=f"physical_slot_{i}",
            roi=(0.1 * (i - 1), 0.0, 0.1 * i, 0.2),
            pick_pose=pose(0.2 + i * 0.01, -0.10 - i * 0.01, 0.30, yaw=i * 0.1),
            empty_depth_mm=800.0,
        )
        for i in range(1, 5)
    )
    destinations = {
        i: DestinationSlot(
            digit=i,
            pose=pose(0.40, -0.05 - i * 0.04, 0.31),
            roi=(0.1 * (i - 1), 0.5, 0.1 * i, 0.7),
            empty_depth_mm=900.0,
        )
        for i in range(1, 5)
    }
    raw = {
        "service": {"allow_motion": True},
        "task2": {
            "verification": {"enabled": verification},
            "approach_height_m": 0.06,
            "travel_speed": 0.08,
            "final_speed": 0.03,
            "preserve_source_orientation": True,
        },
    }
    return RuntimeConfig(
        raw=raw,
        source_slots=sources,
        destination_slots=destinations,
        photo_pose=pose(0.25, -0.16, 0.55),
        safe_pose=pose(0.25, -0.16, 0.60),
    )


class FakeArm:
    def __init__(self, fail_label: str | None = None):
        self.moves: list[tuple[str, Pose6D]] = []
        self.fail_label = fail_label
        self.cancelled = False

    def healthy(self) -> bool:
        return True

    def enable(self) -> None:
        pass

    def current_pose(self) -> Pose6D:
        return pose(0.25, -0.16, 0.55)

    def move_linear(self, target: Pose6D, speed: float, label: str) -> None:
        del speed
        if self.fail_label and self.fail_label in label:
            raise MotionError("模拟动作失败")
        self.moves.append((label, target))

    def cancel(self) -> None:
        self.cancelled = True


class FakeHand:
    def __init__(self):
        self.actions: list[str] = []

    def ensure_ready(self) -> None:
        pass

    def ensure_no_errors(self) -> None:
        pass

    def open(self) -> None:
        self.actions.append("open")

    def grasp_block(self) -> None:
        self.actions.append("grasp")


class FakeVision:
    def __init__(self, observations: list[BlockObservation], fail: bool = False):
        self.observations = observations
        self.fail = fail
        self.verified: list[int] = []

    def acquire_complete_mapping(self, provider):
        provider()
        if self.fail:
            raise VisionError("未得到完整数字集合")
        return self.observations

    def verify_transfer(self, source, destination, expected_digit: int) -> None:
        del source, destination
        self.verified.append(expected_digit)


def randomized_mapping(cfg: RuntimeConfig) -> list[BlockObservation]:
    # 数字并不等于物理槽号：1在槽3、2在槽1、3在槽4、4在槽2。
    digit_to_slot = {1: 3, 2: 1, 3: 4, 4: 2}
    rows = []
    for digit in (1, 2, 3, 4):
        source = cfg.source_slots[digit_to_slot[digit] - 1]
        rows.append(BlockObservation(
            digit=digit,
            source_slot_id=source.slot_id,
            pixel_center=(100.0, 100.0),
            confidence=0.95,
            method="fake",
            pick_pose=source.pick_pose,
            source_yaw=source.pick_pose.yaw,
        ))
    return rows


class ControllerTests(unittest.TestCase):
    def test_randomized_physical_slots_use_actual_pick_poses(self) -> None:
        cfg = runtime()
        arm, hand = FakeArm(), FakeHand()
        result = Task2Controller(cfg, arm, hand, FakeVision(randomized_mapping(cfg))).run()
        self.assertTrue(result.success)
        self.assertEqual(result.completed_digits, (1, 2, 3, 4))
        pick_targets = {
            int(label[2]): target
            for label, target in arm.moves
            if label.endswith("抓取点") and "接近" not in label and "撤回" not in label
        }
        self.assertEqual(pick_targets[1], cfg.source_slots[2].pick_pose)
        self.assertEqual(pick_targets[2], cfg.source_slots[0].pick_pose)
        self.assertEqual(pick_targets[3], cfg.source_slots[3].pick_pose)
        self.assertEqual(pick_targets[4], cfg.source_slots[1].pick_pose)

    def test_four_destinations_are_distinct_and_yaw_is_preserved(self) -> None:
        cfg = runtime()
        arm = FakeArm()
        rows = randomized_mapping(cfg)
        result = Task2Controller(cfg, arm, FakeHand(), FakeVision(rows)).run()
        self.assertTrue(result.success)
        placed = {
            int(label[2]): target
            for label, target in arm.moves
            if label.endswith("放置点") and "接近" not in label and "撤回" not in label
        }
        self.assertEqual(len({(p.x, p.y, p.z) for p in placed.values()}), 4)
        for row in rows:
            self.assertAlmostEqual(placed[row.digit].yaw, row.source_yaw)
            self.assertAlmostEqual(placed[row.digit].roll, row.pick_pose.roll)
            self.assertAlmostEqual(placed[row.digit].pitch, row.pick_pose.pitch)

    def test_incomplete_recognition_never_starts_pick(self) -> None:
        cfg = runtime()
        arm = FakeArm()
        result = Task2Controller(cfg, arm, FakeHand(), FakeVision([], fail=True)).run()
        self.assertFalse(result.success)
        self.assertEqual(result.completed_digits, ())
        self.assertFalse(any("抓取" in label for label, _ in arm.moves))
        self.assertTrue(arm.cancelled)

    def test_partial_motion_failure_is_not_success(self) -> None:
        cfg = runtime()
        arm = FakeArm(fail_label="数字2抓取点")
        result = Task2Controller(cfg, arm, FakeHand(), FakeVision(randomized_mapping(cfg))).run()
        self.assertFalse(result.success)
        self.assertEqual(result.completed_digits, (1,))
        self.assertTrue(arm.cancelled)

    def test_motion_is_locked_by_default_switch(self) -> None:
        cfg = runtime()
        locked = replace(cfg, raw={**cfg.raw, "service": {"allow_motion": False}})
        arm = FakeArm()
        result = Task2Controller(locked, arm, FakeHand(), FakeVision(randomized_mapping(cfg))).run()
        self.assertFalse(result.success)
        self.assertEqual(arm.moves, [])
