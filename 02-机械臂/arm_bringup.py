"""机械臂开机自检（对应任务清单第 2 部分，逐步执行、逐步判定）。

用法：
    python arm_bringup.py --host 192.168.1.100            # 只读检查 + 使能 + plan_only 预览
    python arm_bringup.py --host 192.168.1.100 --move     # 额外做一次真实微动（低速 0.05）

安全约定：
* 默认不做真实运动；真实运动必须显式加 --move。
* 真实微动的目标 = 当前位姿（原地），速度 0.05，先确认空打再谈别的。
* 任何一步失败立即终止并退出码非 0。
"""
from __future__ import annotations

import argparse
import sys

import requests

from arm_client import ArmClient, ArmError

STEPS = []


def step(name: str, ok: bool, detail: str = "") -> None:
    STEPS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name} {detail}")
    if not ok:
        print("\n自检终止：上一步未通过。")
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description="FTArm B9 开机自检")
    ap.add_argument("--host", required=True, help="机械臂服务 IP")
    ap.add_argument("--port", type=int, default=8087)
    ap.add_argument("--side", choices=["right", "left"], default="right")
    ap.add_argument("--move", action="store_true", help="允许真实微动（目标=当前位姿）")
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"
    arm = ArmClient(host=args.host, port=args.port, side=args.side)

    # 1. /api/status 服务可达
    try:
        st = arm.status()
        step("GET /api/status", True, f"moving={st.get('moving')}")
    except Exception as e:
        step("GET /api/status", False, str(e))

    # 2. /api/controllers 健康检查
    try:
        c = requests.get(f"{base}/api/controllers", timeout=5).json()
        step("GET /api/controllers", bool(c.get("joint_state_available")), str(c))
    except Exception as e:
        step("GET /api/controllers", False, str(e))

    # 3. /api/motors 电机健康
    step("GET /api/motors 健康", arm.healthy(), "fault=0 且 has_feedback=1")

    # 4. enable
    try:
        arm.enable()
        step("POST /api/enable", True, "")
    except ArmError as e:
        step("POST /api/enable", False, str(e))
    step("确认 enabled", arm.enabled(), "全部关节 enabled=1")

    # 5. /api/pose 拿当前位姿（TF 未就绪时 pose 为 null：等几秒重试，别直接判死）
    p = None
    for attempt in range(3):
        try:
            p = arm.pose().get("pose")
            if isinstance(p, dict):
                break
        except requests.RequestException as e:
            if attempt == 2:
                step("GET /api/pose", False, str(e))
        if attempt < 2:
            import time
            print(f"  … pose 未就绪（TF 等待中），2s 后重试（第 {attempt + 1}/3 次）")
            time.sleep(2)
    if not isinstance(p, dict):
        step("GET /api/pose", False, "pose 连续 3 次为 null（主栈 TF 未就绪）")
    step("GET /api/pose", True, f"x={p['x']:.3f} y={p['y']:.3f} z={p['z']:.3f}")

    # 5b. 坐标方向断言（左右臂装反/坐标镜像的唯一自动防线）：
    # 右臂工作区 y<0；y 明显为正 = 疑似装反，后面全白干
    y_now = float(p["y"])
    if args.side == "right":
        step("坐标方向(right 臂 y 应<0)", y_now < 0.05,
             f"y={y_now:.3f}" + ("（>0.05 疑似左右臂装反/坐标镜像）" if y_now >= 0.05 else ""))
    else:
        step("坐标方向(left 臂 y 应>0)", y_now > -0.05,
             f"y={y_now:.3f}" + ("（<-0.05 疑似左右臂装反/坐标镜像）" if y_now <= -0.05 else ""))

    # 6. plan_only 预览（目标=当前位姿，不运动；rpy 照搬当前姿态，别用默认 RPY 覆盖）
    cur_rpy = (float(p["roll"]), float(p["pitch"]), float(p["yaw"]))
    try:
        r = arm.line_to(p["x"], p["y"], p["z"], rpy=cur_rpy, vel=0.05, plan_only=True)
        step("plan_only 预览", True, r.get("message", ""))
    except ArmError as e:
        step("plan_only 预览", False, str(e))

    # 7. 真实微动（需 --move）
    if args.move:
        try:
            r = arm.line_to(p["x"], p["y"], p["z"], rpy=cur_rpy, vel=0.05)
            msg = r.get("message", "")
            step("真实微动", True, msg)
        except ArmError as e:
            step("真实微动", False, str(e))
        p2 = arm.pose().get("pose") or {}
        drift = abs(p2.get("x", 0) - p["x"]) + abs(p2.get("y", 0) - p["y"]) + abs(p2.get("z", 0) - p["z"])
        step("到位校验", drift < 0.01, f"漂移 {drift*1000:.1f} mm")
    else:
        print("[SKIP] 真实微动（加 --move 才执行；执行前请清空臂下区域并备好急停）")

    print("\n全部通过。" if not args.move else "\n全部通过（含真实微动）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
