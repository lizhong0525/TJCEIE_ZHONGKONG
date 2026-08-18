from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


class Task2Error(RuntimeError):
    """任务二可向竞赛软件说明的失败。"""


class ConfigError(Task2Error):
    """现场配置不完整或非法。"""


class VisionError(Task2Error):
    """图像、深度、OCR或标定失败。"""


class MotionError(Task2Error):
    """机械臂或灵巧手运动失败。"""


@dataclass(frozen=True)
class Pose6D:
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float

    def with_yaw(self, yaw: float) -> "Pose6D":
        return replace(self, yaw=float(yaw))

    def raised(self, dz: float) -> "Pose6D":
        return replace(self, z=self.z + float(dz))

    def translated(self, xyz: tuple[float, float, float]) -> "Pose6D":
        return replace(
            self,
            x=self.x + float(xyz[0]),
            y=self.y + float(xyz[1]),
            z=self.z + float(xyz[2]),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any], label: str) -> "Pose6D":
        try:
            return cls(*(float(value[k]) for k in ("x", "y", "z", "roll", "pitch", "yaw")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"{label} 必须包含数值 x/y/z/roll/pitch/yaw") from exc


@dataclass(frozen=True)
class RGBDFrame:
    color_bgr: Any
    depth_mm: Any
    intrinsics: tuple[float, float, float, float]


@dataclass(frozen=True)
class DigitReading:
    digit: int
    confidence: float
    method: str


@dataclass(frozen=True)
class BlockObservation:
    """一个数字块与真实物理源槽位的绑定。"""

    digit: int
    source_slot_id: str
    pixel_center: tuple[float, float]
    confidence: float
    method: str
    pick_pose: Pose6D
    source_yaw: float


@dataclass(frozen=True)
class Task2Result:
    success: bool
    message: str
    completed_digits: tuple[int, ...] = ()

