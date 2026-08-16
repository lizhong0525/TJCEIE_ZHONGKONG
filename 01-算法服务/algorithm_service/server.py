"""``aiohttp.web`` HTTP 算法服务。

* 暴露：``GET /api/health``、``POST /api/task1/execute`` 等 4 个端点。
* 任意时刻只有一个赛题在跑：``self._lock`` 串行化。
* 注入 ``runner``（默认走接口示例风格 mock），便于自检与单元测试。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from aiohttp import web

from .config import SiteConfig, load as load_cfg

LOG = logging.getLogger(__name__)


@dataclass
class TaskRunner:
    """业务执行入口。生产实现由 ``app_factory`` 注入；mock 由 selftest 注入。"""

    task1: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    task2: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    task3: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _ok(message: str = "ok") -> web.Response:
    return web.json_response({"success": True, "message": message})


def _fail(message: str) -> web.Response:
    return web.json_response({"success": False, "message": message})


async def _read_json_or_empty(request: web.Request) -> dict[str, Any]:
    if request.method == "GET":
        return {}
    if not request.body_exists:
        return {}
    raw = await request.read()
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise web.HTTPBadRequest(reason="请求体必须是 UTF-8 编码的 JSON")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(reason="请求 JSON 根节点必须是对象")
    return data


def app_factory(
    runner: TaskRunner,
    config_path: str | Path,
) -> web.Application:
    cfg = load_cfg(config_path)

    @web.middleware
    async def error_middleware(request: web.Request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            LOG.exception("未捕获异常：%s", e)
            return _fail(str(e))

    app = web.Application(middlewares=[error_middleware], client_max_size=2 * 1024 * 1024)
    app["cfg"] = cfg
    app["runner"] = runner
    app["lock"] = asyncio.Lock()

    async def health(request: web.Request) -> web.Response:
        return _ok("ready")

    async def task1(request: web.Request) -> web.Response:
        return await _run_task(request, "task1", "task1 ok")

    async def task2(request: web.Request) -> web.Response:
        return await _run_task(request, "task2", "task2 ok")

    async def task3(request: web.Request) -> web.Response:
        return await _run_task(request, "task3", "task3 ok")

    async def _run_task(request: web.Request, key: str, ok_msg: str) -> web.Response:
        body = await _read_json_or_empty(request)
        lock: asyncio.Lock = request.app["lock"]
        if lock.locked():
            return _fail("busy")
        async with lock:
            t0 = time.perf_counter()
            runner: TaskRunner = request.app["runner"]
            fn = getattr(runner, key)
            try:
                result = await fn(body)
            except Exception as e:  # noqa: BLE001
                LOG.warning("赛题 %s 失败: %s", key, e)
                return _fail(str(e) or "task failed")
            elapsed = time.perf_counter() - t0
            LOG.info("赛题 %s 成功，耗时 %.2fs", key, elapsed)
            # 结果摘要进 message：竞赛软件只看 success，但现场人员能从测试工具看到干了啥
            try:
                summary = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                summary = ""
            if summary and summary != "{}":
                if len(summary) > 160:
                    summary = summary[:160] + "…"
                return _ok(f"{ok_msg}: {summary}")
            return _ok(ok_msg)

    app.router.add_get("/api/health", health)
    app.router.add_post("/api/task1/execute", task1)
    app.router.add_post("/api/task2/execute", task2)
    app.router.add_post("/api/task3/execute", task3)
    return app


# ---------------------------------------------------------------------------
# 生产 TaskRunner（用真实 Arm/Hand/Vision）
# ---------------------------------------------------------------------------


def default_runner(cfg: SiteConfig) -> TaskRunner:
    """构造生产用 TaskRunner；硬件/视觉未连接时 ``run`` 抛 ``camera not ready``。"""

    from .hardware import ArmClient, HandClient
    from .vision import Vision
    from .tasks import task1, task2, task3
    from .planner import hand_pose_table

    arm = ArmClient(
        host=cfg.service.arm_host,
        port=cfg.service.arm_port,
        side=cfg.service.arm_side,
    )
    hand = HandClient(
        host=cfg.service.hand_host,
        port=cfg.service.hand_port,
        hand_type=cfg.service.hand_type,
    )
    vision = Vision(
        intrinsics=(cfg.camera.fx, cfg.camera.fy, cfg.camera.cx, cfg.camera.cy),
        distortion=(cfg.distortion.k1, cfg.distortion.k2, cfg.distortion.p1, cfg.distortion.p2),
        hand_eye=cfg.hand_eye.matrix,
    )

    def capture() -> dict[str, Any]:
        f = vision.capture()
        return {"color": f.color, "depth": f.depth}

    async def _run_task1(_: dict[str, Any]) -> dict[str, Any]:
        # 视觉与硬件是同步阻塞，放到默认 executor
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, task1.run, arm, hand, cfg, capture,
        )
        return {"lit_lamp": result.lit_lamp, "actions": result.actions}

    async def _run_task2(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        placed = await loop.run_in_executor(
            None, task2.run, arm, hand, cfg, capture,
        )
        return {"placed": [(b.block_id, b.digit) for b in placed]}

    async def _run_task3(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, task3.run, arm, hand, cfg, capture,
        )
        return {"placed": result.placed, "skipped": result.skipped}

    # 避免 lint 警告 hand_pose_table 未用；如需在 task 内切换姿态可在这里 import
    _ = hand_pose_table

    return TaskRunner(task1=_run_task1, task2=_run_task2, task3=_run_task3)


def run_app(
    config_path: str | Path = "config/site.yaml",
    host: str = "0.0.0.0",
    port: int = 5000,
) -> None:
    cfg = load_cfg(config_path)
    app = app_factory(default_runner(cfg), config_path)
    LOG.info("中控杯算法服务监听 http://%s:%d (config=%s)", host, port, config_path)
    web.run_app(app, host=host, port=port, access_log=None)
