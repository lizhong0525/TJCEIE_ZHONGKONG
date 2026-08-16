"""高层动作库：``safe_home`` / ``retreat_best_effort`` / ``pick`` / ``place``。

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


def ensure_safe(cfg: SiteConfig, target: Pose, label: str) -> None:
    # 占位时直接抛错：未标定就拒绝发任何运动指令
    for axis_name, val in (("x", target.x), ("y", target.y), ("z", target.z)):
        if is_placeholder(val):
            raise SafetyError(f"{label}.{axis_name} 未标定（仍是 __现场标定后填入__）")
    if not cfg.safe_box.contains(target.to_vec3()):
        raise SafetyError(f"{label}={target} 越出安全区")


def pose_from_vec3(v: Vec3, label: str) -> Pose:
    """``Vec3`` → ``Pose``；任一轴是占位/非数值时抛 ``PickError`` 并指明哪根轴。

    所有"配置坐标 → 运动目标"的转换都必须走这里，避免把
    ``float('__现场标定后填入__')`` 的裸 ``ValueError`` 抛给竞赛软件。
    """

    vals: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        val = getattr(v, axis, None)
        if is_placeholder(val):
            raise PickError(f"{label}.{axis} 未标定（仍是 __现场标定后填入__）")
        try:
            vals[axis] = float(val)
        except (TypeError, ValueError):
            raise PickError(f"{label}.{axis} 不是数值：{val!r}") from None
    return Pose(vals["x"], vals["y"], vals["z"])


def safe_home(arm: ArmClient, cfg: SiteConfig, vel: float | None = None) -> None:
    """机械臂回到安全观察位（``cfg.service.safe_home``，可在 site.yaml 改）。"""

    v = cfg.service.safe_home
    if all(is_placeholder(getattr(v, axis)) for axis in ("x", "y", "z")):
        # 三轴全占位 = 完全没标定，只有这种情况才允许用内置默认位兜底
        LOG.warning("service.safe_home 未配置，用内置默认 %s", SAFE_HOME)
        target = SAFE_HOME
    else:
        # 只填了部分轴：半标定坐标和默认位可能差很远，必须报清哪根轴，不能静默换
        target = pose_from_vec3(v, "service.safe_home")
    if is_placeholder(cfg.safe_box.x_min):
        LOG.warning("safe_box 未标定，跳过越界校验，回到 safe_home=%s", target)
    else:
        ensure_safe(cfg, target, "safe_home")
    arm.line_to(target.x, target.y, target.z, vel=vel or cfg.service.safe_vel)


def retreat_best_effort(arm: ArmClient, cfg: SiteConfig) -> None:
    """失败收尾：尽力回安全位；撤不动只告警，不掩盖原始异常（清单 8.6）。"""

    try:
        safe_home(arm, cfg, vel=cfg.service.final_vel)
    except Exception as e:  # noqa: BLE001
        LOG.warning("失败后撤回安全位未成功：%s", e)


def pick(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    target: Pose,
    hand_pose: str,
    pose_table: dict[str, list[float]],
) -> None:
    """标准抓取：open → above → pick → 抓取姿态 → above。"""

    if is_placeholder(cfg.pick.approach_height):
        # 占位时使用默认 0.08 m
        approach_height = 0.08
        LOG.warning("pick.approach_height 未标定，使用 0.08m 兜底")
    else:
        approach_height = float(cfg.pick.approach_height)

    above = Pose(target.x, target.y, target.z + approach_height)
    ensure_safe(cfg, above, "pick.above")
    ensure_safe(cfg, target, "pick.target")

    try:
        hand.pose_name("open", pose_table)
        arm.line_to(above.x, above.y, above.z, vel=cfg.service.safe_vel)
        arm.line_to(target.x, target.y, target.z, vel=cfg.service.final_vel)
        hand.pose_name(hand_pose, pose_table)
        arm.line_to(above.x, above.y, above.z, vel=cfg.service.final_vel)
    except (ArmError, HandError) as e:
        raise PickError(f"pick 失败: {e}") from e


def place(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    slot: Pose,
    pose_table: dict[str, list[float]],
    *, open_after: bool = True,
) -> None:
    """放置：above → slot → open → above。"""

    if is_placeholder(cfg.pick.approach_height):
        approach_height = 0.08
    else:
        approach_height = float(cfg.pick.approach_height)

    above = Pose(slot.x, slot.y, slot.z + approach_height)
    ensure_safe(cfg, above, "place.above")
    ensure_safe(cfg, slot, "place.slot")

    try:
        arm.line_to(above.x, above.y, above.z, vel=cfg.service.safe_vel)
        arm.line_to(slot.x, slot.y, slot.z, vel=cfg.service.final_vel)
        if open_after:
            hand.pose_name("open", pose_table)
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
        "flick": list(h.flick),
    }
