"""赛题 1 —— 控制面板：拍照→识别 6 按钮亮灯→点按 / 拨杆切换→复位。

视觉说明：

* 6 个按钮位置来自 ``cfg.panel.buttons``；按 ``name`` 区分（左红上下2 / 中上黄下
  拨杆 / 右绿上下2）。
* 亮灯识别 = 在按钮中心 ROI 内做颜色阈值 + 圆形度过滤（参数在
  ``config/vision/task1.yaml``）。
* 拨杆：内存里维护 ``toggle_state ∈ {up, down}``；按目标位置在两个槽位间切换。

实现层只提供流程骨架与可替换的 ``detect_lit`` 钩子；亮灯识别阈值在
``task1_vision.py`` 给出最小可用版本（HSV 阈值 + 圆度 + 面积），便于现场调参。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..config import SiteConfig, Vec3, is_placeholder
from ..hardware import ArmClient, ArmError, HandClient, HandError
from ..planner import (
    PickError,
    Pose,
    hand_pose_table,
    safe_home,
)
from .task1_vision import load_params, detect_lit_buttons

LOG = logging.getLogger(__name__)


@dataclass
class Task1Result:
    detected: list[str]
    actions: list[str]


def _button_to_pose(b: Any) -> Pose:
    pos = b.pos
    return Pose(float(pos.x), float(pos.y), float(pos.z))


def run(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    vision_capture: Callable[[], dict[str, Any]] | None = None,
) -> Task1Result:
    """执行一次赛题 1。"""

    if not cfg.panel.buttons:
        raise PickError("panel.buttons 未配置")

    # 1. 启电机 + 复位
    if not arm.healthy():
        raise PickError("机械臂状态不健康")
    if not arm.enabled():
        arm.enable()
    safe_home(arm, cfg, vel=cfg.service.safe_vel)

    # 2. 视觉采集（提供方：实际 Vision 或 mock）
    if vision_capture is None:
        raise PickError("vision_capture 未注入（赛题 1 必须提供一帧彩色图）")
    frame = vision_capture()
    color = frame.get("color")
    if color is None:
        raise PickError("camera not ready")

    # 3. 识别亮灯按钮
    params = load_params()
    detected = detect_lit_buttons(color, cfg.panel.buttons, params)
    LOG.info("task1 detected = %s", detected)

    actions: list[str] = []
    poses = hand_pose_table(cfg)
    with hand.errors_watch():
        for name in detected:
            btn = next((b for b in cfg.panel.buttons if b.name == name), None)
            if btn is None:
                continue
            if is_placeholder(btn.pos.x):
                raise PickError(f"按钮 {name} 坐标未标定（__现场标定后填入__）")
            if btn.kind == "push":
                try:
                    p = _button_to_pose(btn)
                    arm.line_to(p.x, p.y, p.z, vel=cfg.service.final_vel)
                    hand.pose_name("tap", poses)
                    actions.append(f"push:{name}")
                except (ArmError, HandError) as e:
                    raise PickError(f"点按 {name} 失败: {e}") from e
            elif btn.kind == "toggle":
                # 拨杆：内存状态机切到另一侧
                target_attr = f"toggle_state_{name}"
                current = getattr(run, target_attr, "down")
                other = "up" if current == "down" else "down"
                setattr(run, target_attr, other)
                # 复用按钮坐标做 push，模拟拨动
                try:
                    p = _button_to_pose(btn)
                    arm.line_to(p.x, p.y, p.z, vel=cfg.service.final_vel)
                    hand.pose_name("tap", poses)
                    actions.append(f"toggle:{name}->{other}")
                except (ArmError, HandError) as e:
                    raise PickError(f"拨杆 {name} 失败: {e}") from e

    # 4. 复位
    safe_home(arm, cfg, vel=cfg.service.final_vel)
    return Task1Result(detected=detected, actions=actions)
