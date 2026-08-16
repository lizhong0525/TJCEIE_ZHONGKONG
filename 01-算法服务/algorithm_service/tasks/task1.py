"""赛题 1 —— 控制面板：拍照 → 识别唯一亮灯 → 操作其下方开关 → 复位。

真实赛制（判分 30 分 × 3 次）：

* 面板上 3 个指示灯（红/黄/绿），每个灯下方 1 个开关（共 2 个自复位按钮
  + 1 个拨动开关）。竞赛软件随机点亮一个灯调一次本接口，要把亮灯下方
  对应的开关按掉/拨掉。共调 3 次。
* **无状态设计**：服务不记上次灭了哪个灯，每次调用都重新拍照判断。

流程：

1. 健康检查 + enable + 回安全位；
2. 移到 ``cfg.panel.photo_pose`` 拍照位；
3. 拍照 → ``detect_lit_lamp`` 找出唯一亮灯；
4. 按 ``lamp.switch`` 查开关配置，执行点按（push）或拨动（toggle）；
5. 撤回安全位。

任何一步失败：先尽力撤回安全位，再抛 ``PickError``（竞赛软件只看 success）。
拨动方向由配置 ``act_dir`` 固定给出（开关初始状态赛前已知），不存内存状态。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Callable

from ..config import SiteConfig, Switch
from ..hardware import ArmClient, ArmError, HandClient, HandError
from ..planner import (
    PickError,
    Pose,
    ensure_safe,
    hand_pose_table,
    pose_from_vec3,
    retreat_best_effort,
    safe_home,
)
from .task1_vision import load_params, detect_lit_lamp

LOG = logging.getLogger(__name__)


@dataclass
class Task1Result:
    lit_lamp: str
    actions: list[str]


def _actuate(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    sw: Switch,
    poses: dict[str, list[float]],
) -> str:
    """对一个开关执行点按/拨动，返回动作描述串。"""

    pos = pose_from_vec3(sw.pos, f"开关 {sw.name}.pos")
    d = pose_from_vec3(sw.act_dir, f"开关 {sw.name}.act_dir")
    norm = math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z)
    if norm < 1e-6:
        raise PickError(f"开关 {sw.name}.act_dir 是零向量，无法确定作用方向")
    ux, uy, uz = d.x / norm, d.y / norm, d.z / norm

    standoff = float(sw.standoff)
    travel = float(sw.travel)
    approach = Pose(pos.x - ux * standoff, pos.y - uy * standoff, pos.z - uz * standoff)
    ensure_safe(cfg, approach, f"开关 {sw.name} 接近点")
    ensure_safe(cfg, pos, f"开关 {sw.name} 接触点")

    hand_pose = "flick" if sw.kind == "toggle" else "tap"
    try:
        arm.line_to(approach.x, approach.y, approach.z, vel=cfg.service.safe_vel)
        hand.pose_name(hand_pose, poses)
        if sw.kind == "push":
            press = Pose(pos.x + ux * travel, pos.y + uy * travel, pos.z + uz * travel)
            ensure_safe(cfg, press, f"开关 {sw.name} 压入点")
            arm.line_to(press.x, press.y, press.z, vel=cfg.service.final_vel)
            arm.line_to(approach.x, approach.y, approach.z, vel=cfg.service.final_vel)
            action = f"push:{sw.name}"
        elif sw.kind == "toggle":
            drag = Pose(pos.x + ux * travel, pos.y + uy * travel, pos.z + uz * travel)
            ensure_safe(cfg, drag, f"开关 {sw.name} 拨动终点")
            arm.line_to(pos.x, pos.y, pos.z, vel=cfg.service.final_vel)   # 接触
            arm.line_to(drag.x, drag.y, drag.z, vel=cfg.service.final_vel)  # 拨动
            arm.line_to(approach.x, approach.y, approach.z, vel=cfg.service.final_vel)
            action = f"toggle:{sw.name}"
        else:
            raise PickError(f"开关 {sw.name} 类型未知：{sw.kind!r}（应为 push/toggle）")
        hand.pose_name("open", poses)
    except (ArmError, HandError) as e:
        raise PickError(f"操作开关 {sw.name} 失败: {e}") from e
    return action


def run(
    arm: ArmClient,
    hand: HandClient,
    cfg: SiteConfig,
    vision_capture: Callable[[], dict[str, Any]] | None = None,
) -> Task1Result:
    """执行一次赛题 1（处理当前亮着的那个灯）。"""

    # 0. 配置检查（未标定就不许动）
    if not cfg.panel.lamps:
        raise PickError("panel.lamps 未配置")
    if not cfg.panel.switches:
        raise PickError("panel.switches 未配置")
    if vision_capture is None:
        raise PickError("vision_capture 未注入（赛题 1 必须提供一帧彩色图）")
    photo = pose_from_vec3(cfg.panel.photo_pose, "panel.photo_pose")
    ensure_safe(cfg, photo, "panel.photo_pose")

    # 1. 启电机 + 复位
    if not arm.healthy():
        raise PickError("机械臂状态不健康")
    if not arm.enabled():
        arm.enable()
    safe_home(arm, cfg, vel=cfg.service.safe_vel)

    try:
        # 2. 到拍照位 + 拍照
        arm.line_to(photo.x, photo.y, photo.z, vel=cfg.service.safe_vel)
        frame = vision_capture()
        color = frame.get("color") if frame else None
        if color is None:
            raise PickError("camera not ready")

        # 3. 识别唯一亮灯
        lamp_name, invalid = detect_lit_lamp(color, cfg.panel.lamps, load_params())
        if invalid:
            raise PickError(f"灯 ROI 未标定：{invalid}（site.yaml panel.lamps[].roi）")
        if lamp_name is None:
            raise PickError("未检测到亮灯（所有灯 ROI 均未超阈值）")
        LOG.info("task1 亮灯 = %s", lamp_name)
        lamp = next(l for l in cfg.panel.lamps if l.name == lamp_name)

        # 4. 查开关并执行
        sw = next((s for s in cfg.panel.switches if s.name == lamp.switch), None)
        if sw is None:
            raise PickError(
                f"灯 {lamp.name} 指向的开关 {lamp.switch!r} 不在 panel.switches 里"
            )
        poses = hand_pose_table(cfg)
        with hand.errors_watch() as watcher:
            action = _actuate(arm, hand, cfg, sw, poses)
        if watcher.first_error:
            # 8.4：手报错立即中止（走外层撤回）
            raise PickError(f"灵巧手错误码非 0: {watcher.first_error}（按 8.4 停手撤臂）")
        actions = [action]
    except Exception:
        retreat_best_effort(arm, cfg)
        raise

    # 5. 复位
    safe_home(arm, cfg, vel=cfg.service.final_vel)
    return Task1Result(lit_lamp=lamp_name, actions=actions)
