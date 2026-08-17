"""独立已知点验证工具（补齐任务清单 4.4 / 操作指南.md 第 4 节的验收缺口）。

质量门禁（solve_hand_eye）只证明样本"内部自洽"，无法发现系统性错误
（棋盘格边长填错、坐标约定理解错等"每次都偏一点"的问题）。
本工具用一个【没有参加标定】的已知点做外部验收：

两种用法（都需要先完成手眼标定，且标定板/物体保持不动）：

A. 像素模式——先用 check_camera.py 看画面，记下已知点的像素 (u,v)：
   python tools/verify_known_point.py --pixel 320 240 --true 0.412 -0.105 0.305

B. 棋盘格模式——把标定板放到一个新位置（未参与采样），量出棋盘格
   左上角第一个内角点在机械臂基座系的真实坐标：
   python tools/verify_known_point.py --board --true 0.400 -0.120 0.280

判定：计算值与真值的欧氏距离 ≤ 容差（默认 5 mm，--tol 可调）则通过。
不通过 = 标定有系统性错误，回去重标，不得用于真机运动。
"""
from __future__ import annotations

import argparse
import json
import math

import _bootstrap  # noqa: F401
from vision.config import ROOT, load_config, resolve_project_path
from vision.geometry import pixel_to_base, pose_xyzrpy_to_matrix
from vision.models import CameraIntrinsics


def compare(computed: list[float], truth: list[float], tol_m: float) -> tuple[bool, float]:
    """计算值 vs 真值；返回 (是否通过, 误差米)。纯函数，便于离线测试。"""
    err = math.dist(computed, truth)
    return err <= tol_m, err


def _load_calibration(config: dict):
    calib = config["calibration"]
    intr_path = resolve_project_path(calib["intrinsics_result"])
    hand_eye_path = resolve_project_path(calib["hand_eye_result"])
    if not intr_path.exists():
        raise SystemExit(f"缺少内参 {intr_path}，先跑 tools/export_intrinsics.py")
    if not hand_eye_path.exists():
        raise SystemExit(f"缺少手眼标定 {hand_eye_path}，先跑 tools/solve_hand_eye.py")
    hand_eye = json.loads(hand_eye_path.read_text(encoding="utf-8"))
    if not hand_eye.get("quality_gate_passed", False):
        raise SystemExit("手眼标定质量门禁未通过，先重新标定")
    intr = CameraIntrinsics.from_dict(json.loads(intr_path.read_text(encoding="utf-8"))["color_intrinsics"])
    t_end_camera = hand_eye["t_end_camera"]
    return intr, t_end_camera


def main() -> int:
    ap = argparse.ArgumentParser(description="独立已知点验证（手眼标定外部验收）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pixel", nargs=2, type=float, metavar=("U", "V"), help="已知点的像素坐标")
    src.add_argument("--board", action="store_true", help="用棋盘格第一个内角点作为已知点")
    ap.add_argument("--true", nargs=3, type=float, metavar=("X", "Y", "Z"), required=True,
                    help="已知点在机械臂基座系的真实坐标（米，独立量测）")
    ap.add_argument("--tol", type=float, default=0.005, help="容差（米），默认 0.005")
    args = ap.parse_args()

    config = load_config()
    intr, t_end_camera = _load_calibration(config)

    from vision.orbbec_camera import Gemini335Camera
    from vision.robot_client import FTArmPoseClient

    robot = FTArmPoseClient(config)
    with Gemini335Camera(config) as camera:
        frame = camera.capture()
        pose = robot.current_pose()
    t_base_end = pose_xyzrpy_to_matrix(pose)

    if args.pixel:
        u, v = args.pixel
        computed = pixel_to_base(int(u), int(v), frame.depth_mm, intr, t_base_end, t_end_camera)
        label = f"像素({u:.0f},{v:.0f})"
    else:
        from vision.hand_eye import observe_chessboard
        calib = config["calibration"]
        board = tuple(int(x) for x in calib["board_inner_corners"])
        square = float(calib["square_size_m"])
        observation, _ = observe_chessboard(frame.color_bgr, intr, pose, board, square)
        # 棋盘格第一个内角点在相机系中的坐标 → 基座系
        import numpy as np
        t_cam_target = np.eye(4)
        t_cam_target[:3, :3] = observation.r_target_to_camera
        t_cam_target[:3, 3] = observation.t_target_to_camera
        computed = (t_base_end @ np.asarray(t_end_camera) @ t_cam_target @ np.array([0, 0, 0, 1.0]))[:3]
        label = "棋盘格首内角点"

    truth = [float(x) for x in args.true]
    passed, err = compare(list(computed), truth, args.tol)
    print(f"已知点：{label}")
    print(f"  计算值（基座系）：{[round(float(c), 4) for c in computed]}")
    print(f"  真实值（基座系）：{truth}")
    print(f"  误差：{err*1000:.1f} mm（容差 {args.tol*1000:.1f} mm）")
    if passed:
        print("PASS：独立点验收通过，视觉链可用于真机（首次到点仍须高空低速）。")
        return 0
    print("FAIL：误差超容差——标定存在系统性错误（检查棋盘格边长/坐标约定/左右手配置），")
    print("      修正后重新标定并通过质量门禁，再跑一次本工具。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
