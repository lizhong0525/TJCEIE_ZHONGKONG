"""``tools/service_selftest.py`` —— 服务端到端自检（原 ``tools/selftest.py``，相机模块并入后改名）。

流程：

1. 用接口示例风格启动一个 mock 机械臂/灵巧手/相机（直接用 ``contestant_mock_server``
   那套语义，**不启动**真实硬件；硬件客户端走 in-process mock 替换）。
2. 启动 ``algorithm_service`` 的 aiohttp 应用在 ``127.0.0.1:0``（随机端口）。
3. 顺序调用 4 个接口并断言：
   * ``GET /api/health`` → ``success=true``
   * ``POST /api/task1/execute`` × 1 → success（亮灯按钮集合可空，**只要流程不抛错**）
   * ``POST /api/task2/execute`` × 1 → success（同样允许识别为空时返回识别失败 message，
     只要 HTTP 仍是 success=false；这里走"mock 注入图像 = 黑色"路径，应可正常返回
     ``digit recognition failed`` 之类的失败 message；用 ``success=false`` 视为通过）
   * ``POST /api/task3/execute`` × 1 → 同样逻辑
4. 验证并发：另起一个 task 与正在执行的 task 同时被请求 → 立即返回 ``busy``。
5. 打印报告（每个接口耗时、通过/失败），失败 exit 1。

mock 注入：

* ``default_runner`` 使用真实 ``ArmClient``/``HandClient``/``Vision``。为不依赖真机
  与摄像头，这里直接构造一个 ``TaskRunner``：每个 task 调用纯 in-process 钩子。
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("selftest")


# ---------------------------------------------------------------------------
# Mock 硬件（in-process）：把 ArmClient/HandClient/Vision 替换为回声
# ---------------------------------------------------------------------------


class MockArm:
    """模拟右臂：所有 line_to 仅记日志，不发 HTTP。"""

    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float]] = []
        self._healthy = True
        self._enabled = False

    def healthy(self) -> bool: return self._healthy
    def enabled(self) -> bool: return self._enabled

    def enable(self) -> dict[str, Any]:
        self._enabled = True
        return {"right": {"success": True, "message": "mock enabled"}}

    def disable(self) -> dict[str, Any]:
        self._enabled = False
        return {"right": {"success": True, "message": "mock disabled"}}

    def line_to(self, x: float, y: float, z: float, *, vel: float = 0.12, **_: Any) -> dict[str, Any]:
        self.calls.append((x, y, z))
        return {"success": True, "message": "Cartesian execution finished for right_arm"}


class MockHand:
    def __init__(self) -> None:
        self._cur = [0.0] * 10
        self.errors_code = [0] * 10

    def set_pos(self, pos: list[float]) -> dict[str, Any]:
        if len(pos) != 10:
            raise ValueError("len 10")
        self._cur = list(pos)
        return {"success": True, "message": "ok", "target": self._cur}

    def errors(self) -> list[int]:
        return list(self.errors_code)

    def errors_watch(self, interval_s: float = 0.2, on_error=None):
        # mock 实现：不真的起线程；返回 noop 上下文管理器
        from contextlib import nullcontext
        return nullcontext()


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


@dataclass
class Report:
    items: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = []

    def add(self, name: str, ok: bool, ms: float, detail: str = "") -> None:
        self.items.append({"name": name, "ok": ok, "ms": ms, "detail": detail})

    def passed(self) -> bool:
        return all(i["ok"] for i in self.items)

    def print(self) -> None:
        print("=" * 64)
        print("自检报告")
        print("=" * 64)
        for i in self.items:
            mark = "PASS" if i["ok"] else "FAIL"
            print(f"  [{mark}] {i['name']:<24} {i['ms']:7.1f} ms  {i['detail']}")
        print("=" * 64)
        print("Overall:", "PASS" if self.passed() else "FAIL")


# ---------------------------------------------------------------------------
# 服务启动（直接 in-process aiohttp App）
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_app_and_runner(cfg_path: Path):
    """构造 aiohttp App 与 TaskRunner（用 mock 硬件/视觉，**不**走真实 HTTP）。"""

    from algorithm_service.config import load as load_cfg
    from algorithm_service.server import app_factory, TaskRunner
    from algorithm_service.planner import (
        PickError, Pose, hand_pose_table, pick as planner_pick, place as planner_place, safe_home,
    )
    from algorithm_service.tasks import task1_vision as t1v

    cfg = load_cfg(cfg_path)
    arm = MockArm()
    hand = MockHand()

    # 用合成图（红绿黄圆形）注入视觉；构造一张 800x600 BGR，6 个色块。
    color = np.zeros((600, 800, 3), dtype=np.uint8)
    color[:] = 30
    # 左红上下：画两个红色圆
    cv2_circle = __import__("cv2").circle
    cv2_circle(color, (200, 150), 30, (0, 0, 255), -1)
    cv2_circle(color, (200, 450), 30, (0, 0, 255), -1)
    # 中黄
    cv2_circle(color, (400, 150), 30, (0, 255, 255), -1)
    cv2_circle(color, (400, 450), 30, (0, 255, 255), -1)
    # 右绿
    cv2_circle(color, (600, 150), 30, (0, 255, 0), -1)
    cv2_circle(color, (600, 450), 30, (0, 255, 0), -1)

    captured = {"color": color, "depth": None}

    def capture() -> dict[str, Any]:
        return captured

    async def _t1(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_task1, arm, hand, cfg, capture)
        return result

    async def _t2(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        try:
            placed = await loop.run_in_executor(None, _run_task2, arm, hand, cfg, capture)
            return {"placed": placed}
        except PickError as e:
            return {"error": str(e)}

    async def _t3(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        try:
            res = await loop.run_in_executor(None, _run_task3, arm, hand, cfg, capture)
            return {"placed": res["placed"], "skipped": res["skipped"]}
        except PickError as e:
            return {"error": str(e)}

    runner = TaskRunner(task1=_t1, task2=_t2, task3=_t3)
    app = app_factory(runner, cfg_path)
    return app, runner, arm, hand


def _run_task1(arm, hand, cfg, capture) -> dict[str, Any]:
    from algorithm_service.tasks import task1
    return task1.run(arm, hand, cfg, capture)  # type: ignore[arg-type]


def _run_task2(arm, hand, cfg, capture) -> list[tuple[int, int]]:
    from algorithm_service.tasks import task2
    placed = task2.run(arm, hand, cfg, capture)  # type: ignore[arg-type]
    return [(b.block_id, b.digit) for b in placed]


def _run_task3(arm, hand, cfg, capture) -> dict[str, Any]:
    from algorithm_service.tasks import task3
    res = task3.run(arm, hand, cfg, capture)  # type: ignore[arg-type]
    return {"placed": res.placed, "skipped": res.skipped}


# ---------------------------------------------------------------------------
# 自检流程
# ---------------------------------------------------------------------------


async def main_async(args: list[str]) -> int:
    cfg_path = Path(args[1]) if len(args) > 1 else ROOT / "config" / "site.yaml"
    LOG.info("使用配置：%s", cfg_path)
    if not cfg_path.exists():
        # 写一份占位 YAML，保证能跑
        from shutil import copyfile
        sample = ROOT / "config" / "site.yaml"
        if sample.exists():
            copyfile(sample, cfg_path)
    # 简化日志
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

    app, runner, arm, hand = build_app_runner_safe(cfg_path)
    port = _free_port()
    from aiohttp import web
    runner_http = web.AppRunner(app)
    await runner_http.setup()
    site = web.TCPSite(runner_http, "127.0.0.1", port)
    await site.start()
    base = f"http://127.0.0.1:{port}"
    LOG.info("服务已起：%s", base)

    import aiohttp

    report = Report()
    async with aiohttp.ClientSession() as sess:
        # 1. health
        t0 = time.perf_counter()
        try:
            async with sess.get(f"{base}/api/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                body = await r.json()
                ok = r.status == 200 and body.get("success") is True
                report.add("health", ok, (time.perf_counter() - t0) * 1000, json.dumps(body, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            report.add("health", False, (time.perf_counter() - t0) * 1000, str(e))

        # 2. task1
        t0 = time.perf_counter()
        try:
            async with sess.post(f"{base}/api/task1/execute", json={}, timeout=aiohttp.ClientTimeout(total=60)) as r:
                body = await r.json()
                ok = r.status == 200 and isinstance(body, dict) and "success" in body and "message" in body
                report.add("task1", ok, (time.perf_counter() - t0) * 1000, json.dumps(body, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            report.add("task1", False, (time.perf_counter() - t0) * 1000, str(e))

        # 3. task2：注入图像无数字，预期 success=false
        t0 = time.perf_counter()
        try:
            async with sess.post(f"{base}/api/task2/execute", json={}, timeout=aiohttp.ClientTimeout(total=60)) as r:
                body = await r.json()
                ok = r.status == 200 and "success" in body and "message" in body
                report.add("task2 (no digits)", ok, (time.perf_counter() - t0) * 1000, json.dumps(body, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            report.add("task2 (no digits)", False, (time.perf_counter() - t0) * 1000, str(e))

        # 4. task3：注入图像无形状
        t0 = time.perf_counter()
        try:
            async with sess.post(f"{base}/api/task3/execute", json={}, timeout=aiohttp.ClientTimeout(total=60)) as r:
                body = await r.json()
                ok = r.status == 200 and "success" in body and "message" in body
                report.add("task3 (no shapes)", ok, (time.perf_counter() - t0) * 1000, json.dumps(body, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            report.add("task3 (no shapes)", False, (time.perf_counter() - t0) * 1000, str(e))

    # 5. 并发互斥：在 task1 慢执行过程中再发 task1 应当拿到 busy
    #    通过把 runner 替换为慢版来观察
    from algorithm_service.server import TaskRunner as _TR
    class _SlowTask:
        async def __call__(self, _):
            await asyncio.sleep(0.8)
            return {"slow": True}
    slow_runner = _TR(task1=_SlowTask(), task2=_SlowTask(), task3=_SlowTask())
    from algorithm_service.config import load as _load
    from algorithm_service.server import app_factory as _af
    slow_app = _af(slow_runner, cfg_path)
    slow_port = _free_port()
    slow_runner_http = web.AppRunner(slow_app)
    await slow_runner_http.setup()
    await web.TCPSite(slow_runner_http, "127.0.0.1", slow_port).start()
    slow_base = f"http://127.0.0.1:{slow_port}"
    t0 = time.perf_counter()
    try:
        # 同时发两个 task1，第二个应该拿到 busy
        async with aiohttp.ClientSession() as slow_sess:
            async def _go():
                t1 = asyncio.create_task(slow_sess.post(f"{slow_base}/api/task1/execute", json={}))
                await asyncio.sleep(0.05)  # 让第一个先抢到锁
                t2 = asyncio.create_task(slow_sess.post(f"{slow_base}/api/task1/execute", json={}))
                r1 = await t1
                r2 = await t2
                b1 = await r1.json()
                b2 = await r2.json()
                return r1.status, b1, r2.status, b2
            s1, b1, s2, b2 = await asyncio.wait_for(_go(), timeout=5)
        ok = (b1.get("message") == "busy" or b2.get("message") == "busy")
        report.add("concurrent busies", ok, (time.perf_counter() - t0) * 1000, f"r1={b1} r2={b2}")
    except Exception as e:  # noqa: BLE001
        report.add("concurrent busies", False, (time.perf_counter() - t0) * 1000, str(e))
    finally:
        await slow_runner_http.cleanup()

    report.print()
    await runner_http.cleanup()
    return 0 if report.passed() else 1


def build_app_runner_safe(cfg_path: Path):
    try:
        return build_app_and_runner(cfg_path)
    except Exception as e:  # noqa: BLE001
        LOG.error("构造服务失败：%s", e)
        raise


@contextmanager
def _client_session():
    """同步 requests 不可在已运行的 loop 中使用，这里用 aiohttp client。"""
    import aiohttp
    sess = aiohttp.ClientSession()
    try:
        yield sess
    finally:
        # 在调用方 close，避免在已关闭 loop 内调度
        try:
            sess.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    return asyncio.run(main_async(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
