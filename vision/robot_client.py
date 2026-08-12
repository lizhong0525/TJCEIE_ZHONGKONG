from __future__ import annotations

from typing import Any


class RobotPoseError(RuntimeError):
    pass


class FTArmPoseClient:
    """只读FTArm位姿客户端；标定采样时不会发送运动命令。"""

    def __init__(self, config: dict[str, Any]):
        settings = config["robot"]
        self.base_url = str(settings["base_url"]).rstrip("/")
        self.arm = str(settings.get("arm", "right"))
        self.timeout = float(settings.get("request_timeout_seconds", 5))

    def current_pose(self) -> dict[str, float]:
        if "待填写" in self.base_url:
            raise RobotPoseError("config.json中的robot.base_url尚未填写")
        try:
            import requests
        except ImportError as error:
            raise RobotPoseError("未安装requests") from error
        try:
            response = requests.get(self.base_url + "/api/pose", timeout=self.timeout)
            response.raise_for_status()
            value = response.json()
        except Exception as error:
            raise RobotPoseError(f"读取机械臂位姿失败：{error}") from error
        if value.get("arm") not in (None, self.arm):
            raise RobotPoseError(f"机械臂工作区不一致：配置={self.arm}，接口={value.get('arm')}")
        pose = value.get("pose")
        if not isinstance(pose, dict):
            raise RobotPoseError("机械臂接口尚未返回有效pose，请等待主栈TF就绪")
        keys = ("x", "y", "z", "roll", "pitch", "yaw")
        if any(key not in pose for key in keys):
            raise RobotPoseError(f"机械臂pose缺少字段：{pose}")
        return {key: float(pose[key]) for key in keys}
