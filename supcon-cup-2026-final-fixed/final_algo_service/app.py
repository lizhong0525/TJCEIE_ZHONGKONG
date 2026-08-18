"""
中控杯决赛 — 汪汪队算法服务主入口
================================
FastAPI 服务，对接竞赛操作软件

端点:
  GET  /api/health         → 健康检查
  POST /api/task1/execute  → 拨按开关
  POST /api/task2/execute  → 长方体有序转运
  POST /api/task3/execute  → 几何体无序分拣
"""
import os
import time
import logging
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import (
    SERVICE_NAME, SERVICE_VERSION, HOST, PORT,
    TASK_TIMEOUT_MS,
)

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("final-algo")

# ============================================================
# FastAPI 应用
# ============================================================
app = FastAPI(
    title=f"{SERVICE_NAME} - 决赛",
    version=SERVICE_VERSION,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 懒加载模块
# ============================================================
_arm = None
_hand = None
_vision = None


def _get_arm():
    """获取机械臂客户端（懒加载）"""
    global _arm
    if _arm is None:
        from hardware.arm_client import ArmClient
        _arm = ArmClient()
    return _arm


def _get_hand():
    """获取灵巧手客户端（懒加载）"""
    global _hand
    if _hand is None:
        from hardware.hand_client import HandClient
        _hand = HandClient()
    return _hand


def _get_vision():
    """获取视觉模块（懒加载）"""
    global _vision
    if _vision is None:
        from vision.vision_manager import VisionManager
        _vision = VisionManager()
    return _vision


def _release_vision_camera():
    """任务结束后释放 task1/3 的相机设备。

    任务二使用 task2_service 自带的独立采集器（pyorbbecsdk2），
    同一台 Gemini335 同一时间只能被一个管线占用，必须互相让出。
    CameraWrapper.close() 后 _initialized=False，下次 capture 会自动重开。
    """
    cam = getattr(_vision, "_camera", None) if _vision is not None else None
    if cam is not None:
        try:
            cam.close()
        except Exception as e:
            logger.warning(f"释放 task1/3 相机失败: {e}")


# ============================================================
# 任务二（task2_service 独立实现，懒加载 + 并发锁）
# ============================================================
_task2_runtime = None
_task2_run_lock = threading.Lock()
TASK2_CONFIG_PATH = Path(
    os.environ.get("TASK2_CONFIG", str(Path(__file__).resolve().parent / "config.json"))
)


def _get_task2_runtime():
    """构建任务二运行时（配置/相机/OCR/机械臂/灵巧手/控制器）。"""
    global _task2_runtime
    if _task2_runtime is None:
        from task2_service.config import load_config
        from task2_service.camera import Gemini335Camera
        from task2_service.ocr import DigitRecognizer
        from task2_service.hardware import ArmClient as Task2ArmClient
        from task2_service.hardware import HandClient as Task2HandClient
        from task2_service.vision import Task2Vision
        from task2_service.controller import Task2Controller

        config = load_config(TASK2_CONFIG_PATH)
        camera = Gemini335Camera(config.raw["camera"])
        recognizer = DigitRecognizer(config.raw["ocr"])
        arm = Task2ArmClient(config.raw["arm"])
        hand = Task2HandClient(config.raw["hand"])
        vision = Task2Vision(camera, recognizer, config)
        _task2_runtime = (config, camera, Task2Controller(config, arm, hand, vision))
    return _task2_runtime


# ============================================================
# GET / — 根路由（hermes verify readiness 轮询 /，无此路由会 404）
# ============================================================
@app.get("/")
def root() -> Dict[str, Any]:
    return {"success": True, "message": "ready", "docs": "/docs"}


# ============================================================
# GET /api/health — 健康检查
# ============================================================
@app.get("/api/health")
def health() -> Dict[str, Any]:
    """竞赛操作软件通过此端点确认算法服务在线"""
    return {
        "success": True,
        "message": "ready",
    }


# ============================================================
# POST /api/task1/execute — 拨按开关
# ============================================================
@app.post("/api/task1/execute")
def task1_execute() -> Dict[str, Any]:
    """
    任务1：视觉定位亮灯 → 控制机械臂+灵巧手按/拨对应开关。
    竞赛软件每次随机亮一个灯，连续调用三次。
    """
    started = time.perf_counter()
    logger.info("===== 任务1: 拨按开关 开始 =====")

    try:
        from tasks.task1_switch import execute_switch_task

        ok, message = execute_switch_task(
            arm=_get_arm(),
            hand=_get_hand(),
            vision=_get_vision(),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(f"任务1 完成: ok={ok}, message={message}, elapsed={elapsed_ms}ms")

        return {
            "success": ok,
            "message": message,
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error(f"任务1 异常: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"任务1异常: {type(e).__name__}: {str(e)[:200]}",
        }
    finally:
        _release_vision_camera()


# ============================================================
# POST /api/task2/execute — 长方体有序转运
# ============================================================
@app.post("/api/task2/execute")
def task2_execute() -> Dict[str, Any]:
    """
    任务2（task2_service 实现）：
    固定物理槽ROI识别数字 → 集合必须恰为{1,2,3,4}（重拍，绝不猜）
    → 按1→2→3→4从实际槽位抓取 → 放到四个互不重叠的放置点
    → 保留原始姿态 → 每块放完拍照验证 → 四个全成才 success=true。
    """
    started = time.perf_counter()
    logger.info("===== 任务2: 长方体有序转运 开始 =====")

    if not _task2_run_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "任务2正在执行，拒绝重复并发调用",
            "completedDigits": [],
            "elapsedMs": 0,
        }

    camera = None
    try:
        _, camera, controller = _get_task2_runtime()
        result = controller.run()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            f"任务2 完成: success={result.success}, message={result.message}, "
            f"elapsed={elapsed_ms}ms"
        )
        return {
            "success": result.success,
            "message": result.message,
            "completedDigits": list(result.completed_digits),
            "elapsedMs": elapsed_ms,
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error(f"任务2 异常: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"任务2异常: {type(e).__name__}: {str(e)[:200]}",
            "completedDigits": [],
            "elapsedMs": elapsed_ms,
        }
    finally:
        # 释放 USB 相机设备，task1/3 的相机封装才能接着占用
        if camera is not None:
            try:
                camera.stop()
            except Exception as e:
                logger.warning(f"释放任务2相机失败: {e}")
        _task2_run_lock.release()


# ============================================================
# POST /api/task3/execute — 几何体无序分拣
# ============================================================
@app.post("/api/task3/execute")
def task3_execute() -> Dict[str, Any]:
    """
    任务3：识别几何体形状 → 抓取 → 放入对应形状槽位。
    """
    started = time.perf_counter()
    logger.info("===== 任务3: 几何体无序分拣 开始 =====")

    try:
        from tasks.task3_shapes import execute_shape_task

        ok, message = execute_shape_task(
            arm=_get_arm(),
            hand=_get_hand(),
            vision=_get_vision(),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(f"任务3 完成: ok={ok}, message={message}, elapsed={elapsed_ms}ms")

        return {
            "success": ok,
            "message": message,
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error(f"任务3 异常: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"任务3异常: {type(e).__name__}: {str(e)[:200]}",
        }
    finally:
        _release_vision_camera()


# ============================================================
# 启动入口
# ============================================================
if __name__ == "__main__":
    import uvicorn
    logger.info(f"启动 {SERVICE_NAME} v{SERVICE_VERSION} 于 {HOST}:{PORT}")
    logger.info("接口列表:")
    logger.info("  GET  /api/health")
    logger.info("  POST /api/task1/execute")
    logger.info("  POST /api/task2/execute")
    logger.info("  POST /api/task3/execute")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
