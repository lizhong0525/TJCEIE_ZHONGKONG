from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

import re


# COCO 类名到竞赛中文标签的映射
COCO_TO_CN = {
    "person": "人",
    "car": "汽车",
    "bicycle": "自行车",
    "cell phone": "手机",
    "cup": "水杯",
    "laptop": "笔记本电脑",
    "couch": "沙发",
    "dog": "狗",
}

LAMP_CLASSES = ["lamp", "desk lamp", "table lamp"]
LAMP_LABEL = "台灯"

# 模块级单例，首次调用时懒加载
_yolo_model: Optional[Any] = None
_yolo_world_model: Optional[Any] = None
_yolo_world_unavailable: bool = False


def _get_yolo() -> Any:
    """懒加载并返回 ultralytics YOLOv8x 模型。"""
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO

        _yolo_model = YOLO("yolov8x.pt")
    return _yolo_model


def _get_yolo_world() -> Optional[Any]:
    """懒加载并返回 YOLO-World 模型；不可用时返回 None。"""
    global _yolo_world_model, _yolo_world_unavailable
    if _yolo_world_unavailable:
        return None
    if _yolo_world_model is None:
        YOLOWorld: Optional[Any] = None

        # 优先尝试 yolo_world 包，再回退到 ultralytics 内置的 YOLOWorld
        try:
            from yolo_world import YOLOWorld as _YW  # type: ignore

            YOLOWorld = _YW
        except Exception:
            pass

        if YOLOWorld is None:
            try:
                from ultralytics import YOLOWorld as _YW  # type: ignore

                YOLOWorld = _YW
            except Exception:
                pass

        if YOLOWorld is None:
            _yolo_world_unavailable = True
            return None

        # 尝试无参构造，失败则使用常见预训练权重
        try:
            try:
                _yolo_world_model = YOLOWorld()
            except Exception:
                _yolo_world_model = YOLOWorld("yolov8s-worldv2.pt")
            if hasattr(_yolo_world_model, "set_classes"):
                _yolo_world_model.set_classes(LAMP_CLASSES)
        except Exception:
            _yolo_world_model = None
            _yolo_world_unavailable = True
            return None

    return _yolo_world_model


def _extract_boxes(result: Any) -> List[Dict[str, Any]]:
    """从 ultralytics 风格的结果中提取检测框列表。"""
    targets: List[Dict[str, Any]] = []
    if result is None or not hasattr(result, "boxes") or result.boxes is None:
        return targets

    boxes = result.boxes.xyxy
    confs = getattr(result.boxes, "conf", None)
    clses = getattr(result.boxes, "cls", None)
    names = getattr(result, "names", {})

    if boxes is None:
        return targets

    boxes_np = boxes.cpu().numpy() if hasattr(boxes, "cpu") else np.asarray(boxes)
    confs_np = (
        confs.cpu().numpy()
        if confs is not None and hasattr(confs, "cpu")
        else np.asarray(confs) if confs is not None else np.ones(len(boxes_np))
    )
    clses_np = (
        clses.cpu().numpy()
        if clses is not None and hasattr(clses, "cpu")
        else np.asarray(clses) if clses is not None else np.zeros(len(boxes_np))
    )

    for (x1, y1, x2, y2), conf, cls_id in zip(boxes_np, confs_np, clses_np):
        en_name = names.get(int(cls_id), "") if isinstance(names, dict) else ""
        targets.append(
            {
                "label": en_name,
                "cx": float((x1 + x2) / 2.0),
                "cy": float((y1 + y2) / 2.0),
                "score": float(conf),
            }
        )
    return targets


def do_detect(image: Image.Image, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    对输入图像进行目标检测，返回 9 个固定类别的像素中心点。

    - 先用 YOLOv8x 检测 8 个 COCO 类；
    - 再用 YOLO-World 补齐“台灯”类（可选，导入失败时自动跳过）。
    """
    img_rgb = image.convert("RGB")
    img_np = np.asarray(img_rgb)

    targets: List[Dict[str, Any]] = []

    # 1) YOLOv8x 主线检测
    yolo = _get_yolo()
    yolo_results = yolo(img_np, verbose=False)
    yolo_result = yolo_results[0] if isinstance(yolo_results, list) else yolo_results

    for item in _extract_boxes(yolo_result):
        cn_label = COCO_TO_CN.get(item["label"])
        if cn_label:
            targets.append(
                {
                    "label": cn_label,
                    "cx": item["cx"],
                    "cy": item["cy"],
                    "score": item["score"],
                }
            )

    # 2) YOLO-World 台灯补齐（导入失败时静默跳过）
    yw = _get_yolo_world()
    if yw is not None:
        try:
            if hasattr(yw, "set_classes"):
                yw.set_classes(LAMP_CLASSES)
            yw_results = yw(img_np, verbose=False)
            yw_result = yw_results[0] if isinstance(yw_results, list) else yw_results

            for item in _extract_boxes(yw_result):
                targets.append(
                    {
                        "label": LAMP_LABEL,
                        "cx": item["cx"],
                        "cy": item["cy"],
                        "score": item["score"],
                    }
                )
        except Exception:
            # 台灯分支失败不影响主线结果
            pass

    # 在 return 前添加
    for target in targets:
        target["label"] = re.sub(r'\s+', '', target["label"])   # 移除所有空格

    return {"targets": targets}