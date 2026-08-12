"""FTArm B9 机械臂 HTTP 客户端（参考 ``FTArm B9 机械臂HTTP-WS 接口文档.md``）。

设计要点：

* 同步 ``requests`` 客户端，便于在线程中调用。
* 默认右臂工作区，``mode=right_arm`` + 嵌套对象 ``right={x,y,z,roll,pitch,yaw}``。
* ``line_to`` 默认直线 + 速度 ``0.12``；越工作域会触发 OMPL 回退（**不视为失败**）。
* 阻塞上限 60s（HTTP）；用 ``timeout=90`` 兜底。
* 不依赖 ``websockets``；WebSocket 路径留给后续优化（异步进度），不阻塞初版。
"""
from __future__ import annotations

import logging
from typing import Any

import requests

LOG = logging.getLogger(__name__)

DEFAULT_RPY = (-3.141, -1.552, 3.141)  # 已验证推荐姿态


class ArmError(RuntimeError):
    """机械臂业务失败（success=false 或 HTTP 异常）。"""


class ArmClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8087,
        side: str = "right",
        timeout: float = 90.0,
        session: requests.Session | None = None,
    ) -> None:
        if side not in ("right", "left"):
            raise ValueError(f"side must be right/left, got {side!r}")
        self.base = f"http://{host}:{port}"
        self.side = side
        self.timeout = timeout
        self._s = session or requests.Session()

    # ---- 查询 -------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        r = self._s.get(f"{self.base}/api/status", timeout=5)
        r.raise_for_status()
        return r.json()

    def pose(self) -> dict[str, Any]:
        r = self._s.get(f"{self.base}/api/pose", timeout=5)
        r.raise_for_status()
        return r.json()

    def motors(self) -> dict[str, Any]:
        r = self._s.get(f"{self.base}/api/motors", timeout=5)
        r.raise_for_status()
        return r.json()

    def healthy(self) -> bool:
        try:
            m = self.motors()
        except requests.RequestException as e:
            LOG.warning("motors 不可达：%s", e)
            return False
        return bool(m) and all(
            j.get("fault") == 0 and j.get("has_feedback") == 1
            for j in m.values()
        )

    def enabled(self) -> bool:
        try:
            m = self.motors()
        except requests.RequestException:
            return False
        return bool(m) and all(j.get("enabled") == 1 for j in m.values())

    # ---- 电机使能 / 失能 --------------------------------------------------

    def enable(self) -> dict[str, Any]:
        r = self._s.post(f"{self.base}/api/enable", json={}, timeout=15)
        r.raise_for_status()
        body = r.json()
        arm_payload = body.get(self.side) or {}
        if not arm_payload.get("success", False):
            raise ArmError(f"使能失败: {arm_payload.get('message', body)}")
        return body

    def disable(self) -> dict[str, Any]:
        """软急停（手臂会下坠）。正常比赛流程不要主动调用。"""
        r = self._s.post(f"{self.base}/api/disable", json={}, timeout=15)
        r.raise_for_status()
        return r.json()

    # ---- 运动 -------------------------------------------------------------

    def _post_json(self, path: str, body: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        try:
            r = self._s.post(
                f"{self.base}{path}", json=body, timeout=timeout or self.timeout
            )
        except requests.RequestException as e:
            raise ArmError(f"HTTP {path} 失败: {e}") from e
        if r.status_code >= 400:
            raise ArmError(f"HTTP {r.status_code} {path}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise ArmError(f"无法解析 {path} 响应: {r.text[:200]}") from e

    def line_to(
        self,
        x: float,
        y: float,
        z: float,
        *,
        rpy: tuple[float, float, float] = DEFAULT_RPY,
        vel: float = 0.12,
        plan_only: bool = False,
    ) -> dict[str, Any]:
        body = {
            "mode": f"{self.side}_arm",
            self.side: {
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "roll": rpy[0],
                "pitch": rpy[1],
                "yaw": rpy[2],
            },
            "cartesian_linear": True,
            "velocity_scaling": vel,
            "plan_only": plan_only,
        }
        resp = self._post_json("/api/end_effector", body)
        if not resp.get("success", False):
            raise ArmError(resp.get("message", "未知失败"))
        if "OMPL" in (resp.get("message") or ""):
            LOG.warning("直线回退 OMPL（自由路径）：目标=(%s,%s,%s)", x, y, z)
        return resp

    def free_move(
        self,
        x: float,
        y: float,
        z: float,
        *,
        rpy: tuple[float, float, float] = DEFAULT_RPY,
        vel: float = 0.12,
    ) -> dict[str, Any]:
        body = {
            "mode": f"{self.side}_arm",
            self.side: {
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "roll": rpy[0],
                "pitch": rpy[1],
                "yaw": rpy[2],
            },
            "cartesian_linear": False,
            "velocity_scaling": vel,
        }
        resp = self._post_json("/api/end_effector", body)
        if not resp.get("success", False):
            raise ArmError(resp.get("message", "未知失败"))
        return resp

    def joints(self, q7: list[float], vel: float = 0.2) -> dict[str, Any]:
        if len(q7) != 7:
            raise ValueError("joints 需要 7 维数组")
        body = {
            "mode": f"{self.side}_arm",
            f"{self.side}_joints": [float(x) for x in q7],
            "velocity_scaling": vel,
        }
        resp = self._post_json("/api/joints", body, timeout=180)
        if not resp.get("success", False):
            raise ArmError(resp.get("message", "未知失败"))
        return resp

    def cancel(self) -> None:
        try:
            self._s.post(f"{self.base}/api/cancel", json={}, timeout=5)
        except requests.RequestException:
            pass
