from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401
from vision.config import ROOT, load_config, save_json
from vision.hand_eye import observe_chessboard, observation_to_dict
from vision.orbbec_camera import Gemini335Camera
from vision.robot_client import FTArmPoseClient


def main() -> int:
    try:
        import cv2
    except ImportError:
        print("缺少OpenCV，请先安装requirements.txt")
        return 2
    config = load_config()
    calibration = config["calibration"]
    board = tuple(int(v) for v in calibration["board_inner_corners"])
    square = float(calibration["square_size_m"])
    samples_dir = ROOT / "data" / "hand_eye"
    previews_dir = samples_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    samples_path = samples_dir / "samples.json"
    samples = []
    if samples_path.exists():
        samples = json.loads(samples_path.read_text(encoding="utf-8"))
        print(f"已载入原有{len(samples)}组样本")
    robot = FTArmPoseClient(config)
    print("本工具不会移动机械臂。请由操作员低速移动并确保急停可用。")
    print("每组应改变位置和旋转角度；建议至少12组。Enter采样，q退出。")
    with Gemini335Camera(config) as camera:
        while True:
            command = input(f"当前{len(samples)}组。机械臂稳定后按Enter采样（q退出）：").strip().lower()
            if command == "q":
                break
            pose_before = robot.current_pose()
            frame = camera.capture()
            pose_after = robot.current_pose()
            drift = max(abs(pose_before[key] - pose_after[key]) for key in pose_before)
            if drift > 0.001:
                print(f"采样期间机械臂位姿变化过大({drift:.6f})，本次丢弃")
                continue
            try:
                observation, preview = observe_chessboard(
                    frame.color_bgr, frame.intrinsics, pose_before, board, square
                )
            except RuntimeError as error:
                print(f"采样失败：{error}")
                continue
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            cv2.imwrite(str(previews_dir / f"{stamp}.png"), preview)
            item = observation_to_dict(observation)
            item["timestamp"] = frame.timestamp
            item["preview"] = str((Path("previews") / f"{stamp}.png").as_posix())
            samples.append(item)
            save_json(samples_path, samples)
            print(f"采样成功，重投影误差={observation.reprojection_error_px:.3f}px")
    print(f"样本已保存：{samples_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
