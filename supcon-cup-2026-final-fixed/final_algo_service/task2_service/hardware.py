from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .models import MotionError, Pose6D

LOG = logging.getLogger(__name__)


class ArmClient:
    """FTArm B9 HTTP客户端：安全区硬拒绝、直线预规划、禁止OMPL回退。"""

    def __init__(self, settings: dict[str, Any], session: requests.Session | None = None):
        self.settings = settings
        self.base_url = str(settings["base_url"]).rstrip("/")
        self.side = str(settings.get("side", "right"))
        if self.side not in ("right", "left"):
            raise MotionError("arm.side 必须是 right 或 left")
        self.session = session or requests.Session()

    def _get(self, path: str, timeout: float = 5) -> dict[str, Any]:
        try:
            response = self.session.get(f"{self.base_url}{path}", timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise MotionError(f"机械臂 GET {path} 失败: {exc}") from exc

    def _post(self, path: str, body: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        try:
            response = self.session.post(
                f"{self.base_url}{path}",
                json=body,
                timeout=float(timeout or self.settings.get("timeout_s", 90)),
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise MotionError(f"机械臂 POST {path} 失败: {exc}") from exc
        payload = data
        if "success" not in payload:
            payload = data.get(self.side) or data.get("right") or data.get("left") or data
        if not bool(payload.get("success", False)):
            raise MotionError(f"机械臂 {path} 业务失败: {payload.get('message', payload)}")
        return data

    def healthy(self) -> bool:
        motors = self._get("/api/motors")
        values = [v for v in motors.values() if isinstance(v, dict)]
        return bool(values) and all(
            int(v.get("fault", 1)) == 0
            and int(v.get("motor_error", 1)) == 0
            and int(v.get("has_feedback", 0)) == 1
            and float(v.get("feedback_age", 999.0)) < 0.1
            for v in values
        )

    def enable(self) -> None:
        self._post("/api/enable", {})
        time.sleep(0.2)
        motors = self._get("/api/motors")
        values = [v for v in motors.values() if isinstance(v, dict)]
        if not values or not all(int(v.get("enabled", 0)) == 1 for v in values):
            raise MotionError("机械臂使能接口返回后，仍有电机未确认上力")

    def current_pose(self) -> Pose6D:
        body = self._get("/api/pose")
        pose = body.get("pose") or body.get(self.side) or body
        try:
            return Pose6D(*(float(pose[k]) for k in ("x", "y", "z", "roll", "pitch", "yaw")))
        except (KeyError, TypeError, ValueError) as exc:
            raise MotionError(f"机械臂 /api/pose 返回格式异常: {body}") from exc

    def _ensure_safe(self, pose: Pose6D, label: str) -> None:
        box = self.settings["safe_box"]
        for axis, value in (("x", pose.x), ("y", pose.y), ("z", pose.z)):
            low, high = float(box[f"{axis}_min"]), float(box[f"{axis}_max"])
            if not low <= value <= high:
                raise MotionError(f"{label}.{axis}={value:.4f} 超出安全区 [{low},{high}]")

    @staticmethod
    def _ompl_message(body: dict[str, Any]) -> str:
        candidates = [body]
        candidates.extend(v for v in body.values() if isinstance(v, dict))
        for item in candidates:
            message = str(item.get("message", ""))
            if "OMPL" in message.upper():
                return message
        return ""

    def move_linear(self, pose: Pose6D, speed: float, label: str) -> None:
        self._ensure_safe(pose, label)
        target = {
            "x": pose.x, "y": pose.y, "z": pose.z,
            "roll": pose.roll, "pitch": pose.pitch, "yaw": pose.yaw,
        }
        body = {
            "mode": f"{self.side}_arm",
            self.side: target,
            "cartesian_linear": True,
            "velocity_scaling": float(speed),
            "acceleration_scaling": float(speed),
            "cartesian_eef_step": float(self.settings.get("eef_step_m", 0.01)),
            "cartesian_min_fraction": float(self.settings.get("minimum_linear_fraction", 0.98)),
        }
        if bool(self.settings.get("preflight_plan", True)):
            planned = self._post("/api/end_effector", {**body, "plan_only": True})
            message = self._ompl_message(planned)
            if message:
                raise MotionError(f"{label} 不能保持直线，拒绝OMPL绕行: {message}")
        executed = self._post("/api/end_effector", body)
        message = self._ompl_message(executed)
        if message:
            self.cancel()
            raise MotionError(f"{label} 意外发生OMPL回退，已取消: {message}")

    def cancel(self) -> None:
        try:
            self.session.post(f"{self.base_url}/api/cancel", json={}, timeout=5)
        except Exception:
            pass


class HandClient:
    """O10 HTTP客户端；通信失败或非零错误码均视为失败。"""

    def __init__(self, settings: dict[str, Any], session: requests.Session | None = None):
        self.settings = settings
        self.base_url = str(settings["base_url"]).rstrip("/")
        self.session = session or requests.Session()

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = self.session.get(f"{self.base_url}{path}", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise MotionError(f"灵巧手 GET {path} 失败: {exc}") from exc

    def _set(self, values: list[float], label: str) -> None:
        if len(values) != 10 or any(not 0 <= float(v) <= 1 for v in values):
            raise MotionError(f"灵巧手姿态 {label} 必须是10个0~1数值")
        try:
            response = self.session.post(
                f"{self.base_url}/api/set_pos",
                json={"position": [float(v) for v in values]},
                timeout=10,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise MotionError(f"灵巧手设置 {label} 失败: {exc}") from exc
        if not bool(body.get("success", False)):
            raise MotionError(f"灵巧手设置 {label} 失败: {body.get('message', body)}")
        time.sleep(float(self.settings.get("settle_s", 0.35)))
        self.ensure_no_errors()

    def ensure_ready(self) -> None:
        self._get("/api/status")
        self.ensure_no_errors()

    def ensure_no_errors(self) -> None:
        body = self._get("/api/errors")
        codes = body.get("error_codes")
        if not isinstance(codes, list):
            raise MotionError(f"灵巧手错误码响应异常: {body}")
        if any(int(code) != 0 for code in codes):
            raise MotionError(f"灵巧手错误码非0: {codes}")

    def open(self) -> None:
        self._set(list(self.settings["poses"]["open"]), "open")

    def grasp_block(self) -> None:
        self._set(list(self.settings["poses"]["grasp_block"]), "grasp_block")
