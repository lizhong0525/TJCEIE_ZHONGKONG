from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: tuple[float, float, float, float, float]

    @property
    def matrix(self) -> np.ndarray:
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    @property
    def distortion_array(self) -> np.ndarray:
        return np.asarray(self.distortion, dtype=np.float64)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["distortion"] = list(self.distortion)
        value["matrix"] = self.matrix.tolist()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CameraIntrinsics":
        return cls(
            width=int(value["width"]),
            height=int(value["height"]),
            fx=float(value["fx"]),
            fy=float(value["fy"]),
            cx=float(value["cx"]),
            cy=float(value["cy"]),
            distortion=tuple(float(x) for x in value.get("distortion", [0, 0, 0, 0, 0])),
        )


@dataclass(frozen=True)
class FrameBundle:
    color_bgr: np.ndarray
    depth_mm: np.ndarray
    intrinsics: CameraIntrinsics
    timestamp: float
