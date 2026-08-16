"""``aiohttp.web`` HTTP 算法服务。

* 暴露：``GET /api/health``、``POST /api/task1/execute`` 等赛题端点，
  另有 ``GET /``、``GET /api/config/summary`` 调试端点（不动官方契约）。
* 任意时刻只有一个赛题在跑：``self._lock`` 串行化。
* 每次任务请求落一行 JSONL 到 ``service.log_dir``（现场排障不用翻控制台）。
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

from .config import SiteConfig, collect_placeholders, is_placeholder, load as load_cfg

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


def _make_jsonl_logger(cfg: SiteConfig, config_path: str | Path) -> Callable[[dict[str, Any]], None]:
    """每日一个 JSONL 文件；写失败只告警，绝不影响任务执行。"""

    log_dir = Path(cfg.service.log_dir)
    if not log_dir.is_absolute():
        # 相对路径基于项目根（site.yaml 在 <root>/config/ 下）
        log_dir = Path(config_path).resolve().parent.parent / log_dir
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        LOG.warning("JSONL 日志目录创建失败（%s）：%s", log_dir, e)

    def write(entry: dict[str, Any]) -> None:
        path = log_dir / f"{time.strftime('%Y%m%d')}.jsonl"
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:  # noqa: BLE001
            LOG.warning("JSONL 日志写入失败：%s", e)

    return write


def app_factory(
    runner: TaskRunner,
    config_path: str | Path,
    cfg: SiteConfig | None = None,
) -> web.Application:
    # 调用方已加载配置就直接用（run_app 传进来），别重复 load 两次
    cfg = cfg if cfg is not None else load_cfg(config_path)

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
    app["log"] = _make_jsonl_logger(cfg, config_path)

    ENDPOINTS = [
        "GET /",
        "GET /api/health",
        "GET /api/config/summary",
        "POST /api/task1/execute",
        "POST /api/task2/execute",
        "POST /api/task3/execute",
    ]

    async def root(request: web.Request) -> web.Response:
        # 平台若轮询根路由探活，别吃 404（team01 现场教训）
        return _ok("ready")

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"success": True, "message": "ready", "endpoints": ENDPOINTS})

    async def config_summary(request: web.Request) -> web.Response:
        """调试端点：连接信息 + dry_run 回显 + 未标定清单（现场看这一个就够）。"""

        c: SiteConfig = request.app["cfg"]
        camera_calibrated = not (
            is_placeholder(c.camera.fx) or is_placeholder(c.camera.fy)
            or is_placeholder(c.camera.cx) or is_placeholder(c.camera.cy)
        )
        return web.json_response({
            "success": True,
            "message": "ok",
            "arm": {"host": c.service.arm_host, "port": c.service.arm_port, "side": c.service.arm_side},
            "hand": {"host": c.service.hand_host, "port": c.service.hand_port, "type": c.service.hand_type},
            "cameraIntrinsicsCalibrated": camera_calibrated,
            "dryRun": c.service.dry_run,
            "logDir": c.service.log_dir,
            "uncalibrated": collect_placeholders(c),
        })

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
                success, err = True, ""
            except Exception as e:  # noqa: BLE001
                LOG.warning("赛题 %s 失败: %s", key, e)
                success, err = False, str(e) or "task failed"
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if success:
                LOG.info("赛题 %s 成功，耗时 %.2fs", key, elapsed_ms / 1000)
                # 结果摘要进 message：竞赛软件只看 success，但现场人员能从测试工具看到干了啥
                try:
                    summary = json.dumps(result, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    summary = ""
                if summary and summary != "{}":
                    if len(summary) > 160:
                        summary = summary[:160] + "…"
                    message = f"{ok_msg}: {summary}"
                else:
                    message = ok_msg
            else:
                message = err
            # 每次任务落一行 JSONL（排障价值最大的是 elapsed_ms + result_message）
            log_fn = request.app.get("log")
            if log_fn:
                log_fn({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "task": key,
                    "path": request.path,
                    "success": success,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "result_message": message,
                })
            return web.json_response({
                "success": success,
                "message": message,
                "elapsedMs": int(elapsed_ms),
            })

    app.router.add_get("/", root)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/config/summary", config_summary)
    app.router.add_post("/api/task1/execute", task1)
    app.router.add_post("/api/task2/execute", task2)
    app.router.add_post("/api/task3/execute", task3)
    return app


# ---------------------------------------------------------------------------
# 生产 TaskRunner（用真实 Arm/Hand/Vision）
# ---------------------------------------------------------------------------


def _dry_runner() -> TaskRunner:
    """假跑联调：不动硬件，延迟 0.2s 直接 success（验证竞赛软件↔服务契约用）。

    ⚠️ 由 ``service.dry_run: true`` 启用；上场前必须改回 false，否则白跑一场。
    """

    async def _fake(_: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.2)
        return {"dry_run": True}

    return TaskRunner(task1=_fake, task2=_fake, task3=_fake)


def default_runner(cfg: SiteConfig) -> TaskRunner:
    """构造生产用 TaskRunner；硬件/视觉未连接时 ``run`` 抛 ``camera not ready``。"""

    from .hardware import ArmClient, HandClient
    from .tasks import task1, task2, task3
    from .tasks._coords import xyzrpy_to_matrix
    from .vision import Vision

    arm = ArmClient(
        host=cfg.service.arm_host,
        port=cfg.service.arm_port,
        side=cfg.service.arm_side,
        default_rpy=cfg.service.default_rpy,
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
        frame: dict[str, Any] = {"color": f.color, "depth": f.depth}
        # eye-in-hand：坐标解算链是 t_base_end @ t_end_camera，
        # t_base_end 必须用拍照时刻的末端位姿（随臂动变化，不能写死）
        try:
            pose = (arm.pose() or {}).get("pose")
        except Exception as e:  # noqa: BLE001
            pose = None
            LOG.warning("拍照时刻读 /api/pose 失败：%s（涉及深度解算时会报缺 t_base_end）", e)
        if pose:
            frame["t_base_end"] = xyzrpy_to_matrix(pose)
        else:
            LOG.warning("/api/pose 未就绪（TF 未起来或读取失败），本帧无 t_base_end")
        return frame

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
        return {"placed": result.placed, "skipped": result.skipped, "failed": result.failed}

    return TaskRunner(task1=_run_task1, task2=_run_task2, task3=_run_task3)


def run_app(
    config_path: str | Path = "config/site.yaml",
    host: str = "0.0.0.0",
    port: int = 5000,
) -> None:
    cfg = load_cfg(config_path)
    if cfg.service.dry_run:
        LOG.warning("=" * 64)
        LOG.warning("⚠️  DRY-RUN 模式：接口返回 success 但机器人不会动！")
        LOG.warning("⚠️  上场前必须把 site.yaml 的 service.dry_run 改回 false")
        LOG.warning("=" * 64)
    runner = _dry_runner() if cfg.service.dry_run else default_runner(cfg)
    app = app_factory(runner, config_path, cfg)
    LOG.info("中控杯算法服务监听 http://%s:%d (config=%s)", host, port, config_path)
    web.run_app(app, host=host, port=port, access_log=None)
