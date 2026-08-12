"""高层动作库：``safe_home`` / ``approach`` / ``pick`` / ``place`` / ``look_at``。

* 不依赖硬件是否连接：所有硬件方法走 ``ArmClient`` / ``HandClient`` 异常向上抛。
* 安全区校验：所有末端目标先过 ``SiteConfig.safe_box``。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import SiteConfig, Vec3, is_placeholder
from ..hardware import ArmClient, ArmError, HandClient, HandError

LOG = logging.getLogger(__name__)


@dataclass
class Pose:
    x: float
    y: float
    z: float

    def to_vec3(self) -> Vec3:
        return Vec3(x=self.x, y=self.y, z=self.z)


class PickError(RuntimeError):
    """抓取流水线失败。"""


class SafetyError(RuntimeError):
    """目标点越出安全区。"""


SAFE_HOME = Pose(0.275, 0.0, 0.48)  # 中置观察位；只作为相对参考


def _ensure_safe(cfg: SiteConfig, target: Pose, label: str) -> None:
    # 占位时直接抛错：未标定就拒绝发任何运动指令
    for axis_name, val in (("x", target.x), ("y", target.y), ("z", target.z)):
        if is_placeholder(val):
            raise SafetyError(f"{label}.{axis_name} 未标定（仍是 __现场标定后填入__）")
    if not cfg.safe_box.contains(target.to_vec3()):
        raise SafetyError(f"{label}={target} 越出安全区")


def safe_home(arm: ArmClient, cfg: SiteConfig, vel: float | None = None) -> None:
    """机械臂回到安全观察位。"""

    target = SAFE_HOME
    if is_placeholder(cfg.safe_box.x_min):
        LOG.warning("safe_box 未标定，跳过越界校验，回到 safe_home=%s", target)
    else:
        _ensure_safe(cfg, target, "safe_home")
    arm.line_to(target.x, target.y, target.z, vel=vel or cfg.service.safe_vel)


def look_at(arm: ArmClient, cfg: SiteConfig, target: Pose) -> None:
    """移动到目标上方的观察位（z 抬到 target.z + 0.10 m，仅参考）。"""

    above = Pose(target.x, target.y, target.z + 0.10)
    if is_placeholder(cfg.safe_box.x_min):
        LOG.warning("safe_box 未标定，look_at 跳过越界校验 -> %s", above)
    else:
        _ensure_safe(cfg, above, "look_at")
    arm.line_to(above.x, above.y, above.z, vel=cfg.service.safe_vel)


def approach(arm: ArmClient, cfg: SiteConfig, target: Pose) -> None:
    """从上方下降到目标正上方 0.02 m。"""

    above = Pose(target.x, target.y, target.z + 0.02)
    _ensure_safe(cfg, above, "approach")
    arm.line_to(above.x, above.y, above.z, vel=cfg.service.safe_vel)


def pick(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    target: Pose,
    hand_pose: str,
    hand_pose_table: dict[str, list[float]],
) -> None:
    """标准抓取：open → above → pick → 抓取姿态 → above。"""

    if is_placeholder(cfg.pick.approach_height):
        # 占位时使用默认 0.08 m
        approach_height = 0.08
        LOG.warning("pick.approach_height 未标定，使用 0.08m 兜底")
    else:
        approach_height = float(cfg.pick.approach_height)

    above = Pose(target.x, target.y, target.z + approach_height)
    _ensure_safe(cfg, above, "pick.above")
    _ensure_safe(cfg, target, "pick.target")

    try:
        hand.pose_name("open", hand_pose_table)
        arm.line_to(above.x, above.y, above.z, vel=cfg.service.safe_vel)
        arm.line_to(target.x, target.y, target.z, vel=cfg.service.final_vel)
        hand.pose_name(hand_pose, hand_pose_table)
        arm.line_to(above.x, above.y, above.z, vel=cfg.service.final_vel)
    except (ArmError, HandError) as e:
        raise PickError(f"pick 失败: {e}") from e


def place(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    slot: Pose,
    hand_pose_table: dict[str, list[float]],
    *, open_after: bool = True,
) -> None:
    """放置：above → slot → open → above。"""

    if is_placeholder(cfg.pick.approach_height):
        approach_height = 0.08
    else:
        approach_height = float(cfg.pick.approach_height)

    above = Pose(slot.x, slot.y, slot.z + approach_height)
    _ensure_safe(cfg, above, "place.above")
    _ensure_safe(cfg, slot, "place.slot")

    try:
        arm.line_to(above.x, above.y, above.z, vel=cfg.service.safe_vel)
        arm.line_to(slot.x, slot.y, slot.z, vel=cfg.service.final_vel)
        if open_after:
            hand.pose_name("open", hand_pose_table)
        arm.line_to(above.x, above.y, above.z, vel=cfg.service.final_vel)
    except (ArmError, HandError) as e:
        raise PickError(f"place 失败: {e}") from e


def hand_pose_table(cfg: SiteConfig) -> dict[str, list[float]]:
    h = cfg.hand
    return {
        "open": list(h.open),
        "close": list(h.close),
        "grasp_digit": list(h.grasp_digit),
        "grasp_shape": list(h.grasp_shape),
        "tap": list(h.tap),
    }
