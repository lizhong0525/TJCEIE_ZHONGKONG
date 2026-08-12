from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .geometry import matrix_to_json, pose_xyzrpy_to_matrix
from .models import CameraIntrinsics


@dataclass(frozen=True)
class BoardObservation:
    t_base_end: np.ndarray
    r_target_to_camera: np.ndarray
    t_target_to_camera: np.ndarray
    reprojection_error_px: float


def chessboard_object_points(inner_corners: tuple[int, int], square_size_m: float) -> np.ndarray:
    columns, rows = inner_corners
    points = np.zeros((columns * rows, 3), dtype=np.float32)
    points[:, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2)
    points[:, :2] *= float(square_size_m)
    return points


def observe_chessboard(
    color_bgr: np.ndarray,
    intr: CameraIntrinsics,
    robot_pose: dict[str, float],
    inner_corners: tuple[int, int],
    square_size_m: float,
) -> tuple[BoardObservation, np.ndarray]:
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("手眼标定需要opencv-contrib-python") from error
    gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
    found, corners = cv2.findChessboardCornersSB(
        gray,
        inner_corners,
        flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY,
    )
    if not found:
        raise RuntimeError("没有检测到完整棋盘格，请调整距离、角度、光照并确保所有内角可见")
    object_points = chessboard_object_points(inner_corners, square_size_m)
    ok, rvec, tvec = cv2.solvePnP(
        object_points,
        corners,
        intr.matrix,
        intr.distortion_array,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        raise RuntimeError("棋盘格PnP位姿求解失败")
    projected, _ = cv2.projectPoints(
        object_points, rvec, tvec, intr.matrix, intr.distortion_array
    )
    error = float(np.mean(np.linalg.norm(projected.reshape(-1, 2) - corners.reshape(-1, 2), axis=1)))
    rotation, _ = cv2.Rodrigues(rvec)
    observation = BoardObservation(
        pose_xyzrpy_to_matrix(robot_pose),
        rotation.astype(np.float64),
        tvec.reshape(3).astype(np.float64),
        error,
    )
    preview = color_bgr.copy()
    cv2.drawChessboardCorners(preview, inner_corners, corners, found)
    cv2.putText(
        preview,
        f"reprojection={error:.3f}px",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2,
    )
    return observation, preview


def observation_to_dict(value: BoardObservation) -> dict[str, Any]:
    return {
        "t_base_end": matrix_to_json(value.t_base_end),
        "r_target_to_camera": value.r_target_to_camera.tolist(),
        "t_target_to_camera_m": value.t_target_to_camera.tolist(),
        "reprojection_error_px": value.reprojection_error_px,
    }


def observation_from_dict(value: dict[str, Any]) -> BoardObservation:
    return BoardObservation(
        np.asarray(value["t_base_end"], dtype=np.float64),
        np.asarray(value["r_target_to_camera"], dtype=np.float64),
        np.asarray(value["t_target_to_camera_m"], dtype=np.float64),
        float(value["reprojection_error_px"]),
    )


def _rotation_angle(rotation: np.ndarray) -> float:
    cosine = np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0)
    return float(math.acos(cosine))


def solve_eye_in_hand(observations: list[BoardObservation]) -> dict[str, Any]:
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("手眼标定需要opencv-contrib-python") from error
    if len(observations) < 3:
        raise ValueError("OpenCV至少需要3组数据；实操建议12组以上且角度变化充分")
    rotations_gripper_to_base = [item.t_base_end[:3, :3] for item in observations]
    translations_gripper_to_base = [item.t_base_end[:3, 3].reshape(3, 1) for item in observations]
    rotations_target_to_camera = [item.r_target_to_camera for item in observations]
    translations_target_to_camera = [item.t_target_to_camera.reshape(3, 1) for item in observations]
    r_camera_to_gripper, t_camera_to_gripper = cv2.calibrateHandEye(
        rotations_gripper_to_base,
        translations_gripper_to_base,
        rotations_target_to_camera,
        translations_target_to_camera,
        method=cv2.CALIB_HAND_EYE_PARK,
    )
    t_end_camera = np.eye(4, dtype=np.float64)
    t_end_camera[:3, :3] = r_camera_to_gripper
    t_end_camera[:3, 3] = t_camera_to_gripper.reshape(3)

    target_in_base = []
    for item in observations:
        t_camera_target = np.eye(4, dtype=np.float64)
        t_camera_target[:3, :3] = item.r_target_to_camera
        t_camera_target[:3, 3] = item.t_target_to_camera
        target_in_base.append(item.t_base_end @ t_end_camera @ t_camera_target)
    translations = np.asarray([value[:3, 3] for value in target_in_base])
    translation_center = translations.mean(axis=0)
    translation_errors = np.linalg.norm(translations - translation_center, axis=1)
    reference_rotation = target_in_base[0][:3, :3]
    rotation_errors = [
        _rotation_angle(reference_rotation.T @ value[:3, :3]) for value in target_in_base
    ]
    reprojection = [item.reprojection_error_px for item in observations]
    return {
        "transform_name": "T_end_camera",
        "meaning": "将彩色相机坐标中的点转换到机械臂末端坐标",
        "t_end_camera": matrix_to_json(t_end_camera),
        "sample_count": len(observations),
        "quality": {
            "mean_reprojection_error_px": float(np.mean(reprojection)),
            "max_reprojection_error_px": float(np.max(reprojection)),
            "mean_target_translation_spread_m": float(np.mean(translation_errors)),
            "max_target_translation_spread_m": float(np.max(translation_errors)),
            "max_target_rotation_spread_deg": float(np.degrees(max(rotation_errors))),
        },
    }
