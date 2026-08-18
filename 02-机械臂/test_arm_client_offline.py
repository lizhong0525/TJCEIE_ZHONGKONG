"""arm_client 离线测试：用 stdlib 起一个假 B9 服务，验证客户端解析与报错路径。

运行：python test_arm_client_offline.py
不依赖真机、不依赖第三方库（arm_client 本身只用 requests）。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from arm_client import ArmClient, ArmError

JOINTS = [
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint",
    "right_elbow_roll_joint", "right_elbow_yaw_joint", "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
]


class MockB9(BaseHTTPRequestHandler):
    enabled = 0  # 类级状态：enable 后变 1

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self._send({"timestamp": 1.0, "moving": False, "moveit_available": True,
                        "right_joints": {}, "right_pose": None})
        elif self.path == "/api/pose":
            self._send({"arm": "right", "pose": {"x": 0.275, "y": -0.16, "z": 0.48,
                        "roll": -3.141, "pitch": -1.552, "yaw": 3.141}})
        elif self.path == "/api/motors":
            self._send({j: {"position": 0.0, "velocity": 0.0, "effort": 0.0,
                            "motor_error": 0, "fault": 0, "has_feedback": 1,
                            "feedback_age": 0.01, "enabled": type(self).enabled}
                        for j in JOINTS})
        elif self.path == "/api/controllers":
            self._send({"joint_state_available": True, "active": False})
        else:
            self._send({"success": False, "message": "unknown"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/enable":
            type(self).enabled = 1
            self._send({"right": {"success": True, "message": "7 motors enabled"}})
        elif self.path == "/api/end_effector":
            target = body.get("right") or {}
            if target.get("z", 0) > 0.6:  # 模拟不可达
                self._send({"success": False,
                            "message": "All planning strategies failed for right_arm"}, 400)
            elif target.get("x", 0) > 0.4:  # 模拟直线回退 OMPL
                self._send({"success": True, "message": "OMPL execution finished for right_arm"})
            elif body.get("plan_only"):
                self._send({"success": True, "message": "Planning succeeded (not executed)"})
            else:
                self._send({"success": True, "message": "Cartesian execution finished for right_arm"})
        elif self.path == "/api/joints":
            q = body.get("right_joints")
            if not isinstance(q, list) or len(q) != 7:
                self._send({"success": False, "message": "Invalid joint array"}, 400)
            else:
                self._send({"success": True, "message": "Joint motion executed"})
        else:
            self._send({"success": False, "message": "unknown"}, 404)

    def log_message(self, *a) -> None:  # 静音
        pass


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockB9)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    arm = ArmClient(host="127.0.0.1", port=port, side="right")

    passed = 0

    def ok(name: str, cond: bool, extra: str = "") -> None:
        nonlocal passed
        assert cond, f"FAIL {name} {extra}"
        passed += 1
        print(f"PASS {name} {extra}")

    # 状态/位姿/控制器解析
    ok("status", arm.status().get("moveit_available") is True)
    pose = arm.pose()["pose"]
    ok("pose", abs(pose["x"] - 0.275) < 1e-9)

    # 使能前 enabled=False，使能后 True
    ok("enable 前未使能", arm.enabled() is False)
    arm.enable()
    ok("enable 后已使能", arm.enabled() is True)
    ok("healthy", arm.healthy() is True)

    # 正常直线运动
    r = arm.line_to(0.275, -0.16, 0.48)
    ok("line_to 成功", "Cartesian" in r["message"])

    # plan_only
    r = arm.line_to(0.275, -0.16, 0.48, plan_only=True)
    ok("plan_only", "Planning succeeded" in r["message"])

    # 不可达 → ArmError，message 透传
    try:
        arm.line_to(0.275, -0.16, 0.9)
        raise SystemExit("FAIL: 不可达目标没有抛 ArmError")
    except ArmError as e:
        ok("不可达抛 ArmError", "planning strategies failed" in str(e), str(e))

    # OMPL/RRT 回退：客户端抛 ArmError 按失败处理（运动已执行完，业务层走失败撤回；
    # 只告警不抛错时业务层拿不到 message 会当成功——静默走错路径比明确失败危险）
    try:
        arm.line_to(0.45, -0.16, 0.48)
        raise SystemExit("FAIL: OMPL 回退没有抛 ArmError")
    except ArmError as e:
        ok("OMPL 回退抛 ArmError", "回退自由路径" in str(e), str(e))

    # joints 参数校验与正常执行
    try:
        arm.joints([0.1, 0.2])
        raise SystemExit("FAIL: 非 7 维 joints 没有抛错")
    except ValueError:
        ok("joints 非 7 维拒绝", True)
    ok("joints 正常", "executed" in arm.joints([0, 0.5, 0, -1, -0.1, -1, 0])["message"])

    srv.shutdown()
    print(f"\n全部 {passed} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
