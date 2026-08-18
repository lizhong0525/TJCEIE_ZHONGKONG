"""``tools/debug_console.py`` —— 标定日交互式调试控制台。

省掉"读位姿 → 手誊进 site.yaml"的抄写环节：读到的坐标直接打印成可粘贴的
yaml 行。菜单：

1. 读末端位姿 → 打印 ``{x: ..., y: ..., z: ...}``（可直接粘进 site.yaml）
2. 直线 Jog（输入 x y z，走 default_rpy）
3. 关节 Jog（输入 7 维角度）
4. 手型测试（open/close/grasp_digit/grasp_shape/tap/flick 逐个发）
5. 相机拍照存图（存到 output/ 下）
6. 模拟竞赛软件调用（POST 本机服务的 task1/2/3）
7. 回安全位（service.safe_home）
0. 退出

用法：``python -m tools.debug_console``（在 01-算法服务/ 下）。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_service.config import load as load_cfg  # noqa: E402


def _yaml_vec3(x: float, y: float, z: float) -> str:
    return f"{{x: {x:.4f}, y: {y:.4f}, z: {z:.4f}}}"


def main() -> int:
    cfg = load_cfg(ROOT / "config" / "site.yaml")
    svc = cfg.service

    from algorithm_service.hardware import ArmClient, HandClient

    arm = ArmClient(host=svc.arm_host, port=svc.arm_port, side=svc.arm_side,
                    default_rpy=svc.default_rpy)
    hand = HandClient(host=svc.hand_host, port=svc.hand_port, hand_type=svc.hand_type)

    menu = (
        "\n===== 调试控制台 =====\n"
        "1. 读末端位姿（打印可粘贴 yaml）\n"
        "2. 直线 Jog（x y z）\n"
        "3. 关节 Jog（7 维）\n"
        "4. 手型测试\n"
        "5. 相机拍照存图\n"
        "6. 模拟竞赛软件调 task 接口\n"
        "7. 回安全位\n"
        "0. 退出\n"
        "> "
    )
    while True:
        try:
            choice = input(menu).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        try:
            if choice == "1":
                pose = (arm.pose() or {}).get("pose")
                if not pose:
                    print("  /api/pose 返回 null（TF 未就绪），等几秒重试")
                    continue
                print(f"  pos: {_yaml_vec3(pose['x'], pose['y'], pose['z'])}")
                print(f"  rpy: [{pose['roll']:.4f}, {pose['pitch']:.4f}, {pose['yaw']:.4f}]")
                print("  ↑ 直接粘进 site.yaml 对应坐标项")
            elif choice == "2":
                x, y, z = (float(v) for v in input("  x y z (m): ").split())
                r = arm.line_to(x, y, z, vel=svc.safe_vel)
                print(f"  {r.get('message')}")
            elif choice == "3":
                q = [float(v) for v in input("  7 维关节角: ").split()]
                r = arm.joints(q)
                print(f"  {r.get('message')}")
            elif choice == "4":
                from algorithm_service.planner import hand_pose_table

                table = hand_pose_table(cfg)
                name = input(f"  手型 {sorted(table)}: ").strip()
                hand.pose_name(name, table)
                print(f"  {name} 已下发")
            elif choice == "5":
                from algorithm_service.vision import Vision

                vision = Vision(
                    intrinsics=(cfg.camera.fx, cfg.camera.fy, cfg.camera.cx, cfg.camera.cy),
                    hand_eye=cfg.hand_eye.matrix if not _has_placeholder(cfg) else None,
                )
                try:
                    frame = vision.capture(timeout_ms=2000)
                    out = ROOT / "output"
                    out.mkdir(exist_ok=True)
                    import cv2

                    path = out / f"debug_{int(time.time())}.png"
                    # 中文路径下 imwrite 可能静默失败（返回 False），必须查返回值
                    if not cv2.imwrite(str(path), frame.color):
                        print(f"  ! 存图失败（中文路径？）：{path}")
                    else:
                        print(f"  已存 {path}")
                finally:
                    vision.close()
            elif choice == "6":
                task = input("  task1/task2/task3: ").strip()
                if task not in ("task1", "task2", "task3"):
                    print("  无效")
                    continue
                req = urllib.request.Request(
                    f"http://127.0.0.1:5000/api/{task}/execute",
                    data=b"{}", headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=300) as r:
                    body = json.loads(r.read().decode("utf-8"))
                print(f"  success={body.get('success')}  message={body.get('message')}")
            elif choice == "7":
                from algorithm_service.planner import safe_home

                safe_home(arm, cfg)
                print("  已回安全位")
            elif choice == "0":
                return 0
        except Exception as e:  # noqa: BLE001
            print(f"  失败: {e}")


def _has_placeholder(cfg) -> bool:
    from algorithm_service.config import collect_placeholders

    return any(p.startswith("hand_eye") for p in collect_placeholders(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
