"""``tools/service_selftest.py`` —— 服务端到端自检。

历史教训（假绿灯）：旧版 mock 把 ``PickError`` 吞成 ``{"error": ...}`` 正常返回，
断言又只看"响应里有 success 字段"——于是 task2 识别全空、task1 因 mock 缺
``pose_name`` 崩成 AttributeError，报告照样全 PASS。本版原则：

* **失败路径必须断言 ``success == false`` 且 message 含预期原因**；
* **成功路径必须断言 ``success == true`` 且硬件 mock 收到了预期动作**
  （臂到过开关坐标、手切过预期手型），不是"没抛错就算过"。

场景：

1. ``GET /api/health`` → success=true。
2. task1 亮红灯 → success=true，且走了 push 序列（接近点/压入点坐标断言）。
3. task1 亮绿灯 → success=true，且走了 toggle 序列（接触点/拨动终点断言）。
4. task1 无灯亮 → success=false，message 含"未检测到亮灯"。
5. task2 空图 → success=false，message 含"digit recognition failed"。
6. task3 三种形状合成图 → success=true，placed=3，臂到过 3 个槽位。
7. task3 空图 → success=false，message 含"shape recognition failed"。
8. 全占位配置（未标定）：task1 → "panel.lamps 未配置"；task3 → "未标定"
   （且绝不是裸 ValueError 的 "could not convert"）。
9. 并发互斥：执行中再发同题 → 第二个拿到 busy。

用法：``python -m tools.service_selftest``，失败 exit 1。
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("selftest")

# ---------------------------------------------------------------------------
# Mock 硬件（in-process）
# ---------------------------------------------------------------------------


class MockArm:
    """模拟右臂：所有 line_to 只记录坐标，不发 HTTP。"""

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

    def visited(self, x: float, y: float, z: float, tol: float = 1e-6) -> bool:
        return any(
            abs(cx - x) < tol and abs(cy - y) < tol and abs(cz - z) < tol
            for cx, cy, cz in self.calls
        )


class MockHand:
    def __init__(self) -> None:
        self.poses: list[str] = []
        self.errors_code = [0] * 10

    def set_pos(self, position: list[float]) -> dict[str, Any]:
        if len(position) != 10:
            raise ValueError("len 10")
        return {"success": True, "message": "ok"}

    def pose_name(self, name: str, table: dict[str, list[float]]) -> dict[str, Any]:
        if name not in table:
            raise KeyError(f"未知手型 {name!r}")
        self.poses.append(name)
        return {"success": True, "message": "ok"}

    def errors(self) -> list[int]:
        return list(self.errors_code)

    def errors_watch(self, interval_s: float = 0.2, on_error=None):
        return nullcontext()  # mock：不起线程


# ---------------------------------------------------------------------------
# 全标定 mock 配置（所有坐标落在 safe_box 内）
# ---------------------------------------------------------------------------

SAFE_BOX = {"x_min": 0.05, "x_max": 0.60, "y_min": -0.35, "y_max": 0.35,
            "z_min": 0.30, "z_max": 0.60}

# 灯 ROI（拍照位像素坐标，对应 800x600 图）
ROI_RED = [100, 80, 260, 240]
ROI_YELLOW = [330, 80, 490, 240]
ROI_GREEN = [560, 80, 720, 240]

# 开关坐标（基座系 m）
SW_RED = {"x": 0.32, "y": -0.20, "z": 0.46}
SW_YELLOW = {"x": 0.30, "y": -0.20, "z": 0.46}
SW_TOGGLE = {"x": 0.28, "y": -0.20, "z": 0.46}

MOCK_CFG_RAW: dict[str, Any] = {
    "service": {"arm_host": "127.0.0.1", "arm_port": 8087, "arm_side": "right",
                "hand_host": "127.0.0.1", "hand_port": 8088, "hand_type": "right",
                "safe_vel": 0.12, "final_vel": 0.05},
    "camera": {"fx": 600.0, "fy": 600.0, "cx": 400.0, "cy": 300.0},
    "distortion": {"k1": 0.0, "k2": 0.0, "p1": 0.0, "p2": 0.0},
    "hand_eye": {"rows": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]},
    "safe_box": SAFE_BOX,
    "pick": {"approach_height": 0.05},
    "hand": {"poses": {
        "open": [1.0] * 10, "close": [0.0] * 10, "grasp_digit": [0.0] * 10,
        "grasp_shape": [0.0] * 10, "tap": [0.0] * 10, "flick": [0.0] * 10,
    }},
    "panel": {
        "photo_pose": {"x": 0.30, "y": -0.15, "z": 0.50},
        "lamps": [
            {"name": "lamp_red", "color": "red", "switch": "btn_red", "roi": ROI_RED},
            {"name": "lamp_yellow", "color": "yellow", "switch": "btn_yellow", "roi": ROI_YELLOW},
            {"name": "lamp_green", "color": "green", "switch": "sw_toggle", "roi": ROI_GREEN},
        ],
        "switches": [
            {"name": "btn_red", "kind": "push", "pos": SW_RED,
             "act_dir": {"x": 0, "y": -1, "z": 0}, "travel": 0.005, "standoff": 0.05},
            {"name": "btn_yellow", "kind": "push", "pos": SW_YELLOW,
             "act_dir": {"x": 0, "y": -1, "z": 0}, "travel": 0.005, "standoff": 0.05},
            {"name": "sw_toggle", "kind": "toggle", "pos": SW_TOGGLE,
             "act_dir": {"x": 0, "y": 0, "z": -1}, "travel": 0.02, "standoff": 0.05},
        ],
    },
    "digit_blocks": {
        "expected_count": 4,
        "placement_order_target": "ascending",
        "staging_area": {"x": 0.25, "y": -0.12, "z": 0.45},
        "placement_area": {"x": 0.32, "y": -0.25, "z": 0.45},
        "slots": [
            {"name": f"slot_{i+1}", "pos": {"x": 0.30 + 0.02 * i, "y": -0.25, "z": 0.45}}
            for i in range(4)
        ],
    },
    "shapes": {
        "staging_area": {"x": 0.25, "y": -0.12, "z": 0.45},
        "kinds": [
            {"name": "round", "slots": [
                {"name": "round_slot_1", "pos": {"x": 0.30, "y": -0.25, "z": 0.45}},
                {"name": "round_slot_2", "pos": {"x": 0.32, "y": -0.25, "z": 0.45}},
            ]},
            {"name": "square", "slots": [
                {"name": "square_slot_1", "pos": {"x": 0.34, "y": -0.25, "z": 0.45}},
                {"name": "square_slot_2", "pos": {"x": 0.36, "y": -0.25, "z": 0.45}},
            ]},
            {"name": "irregular", "slots": [
                {"name": "irregular_slot_1", "pos": {"x": 0.38, "y": -0.25, "z": 0.45}},
            ]},
        ],
    },
}


# ---------------------------------------------------------------------------
# 合成图
# ---------------------------------------------------------------------------


def panel_image(lit: str | None) -> np.ndarray:
    """800x600 面板图；``lit`` ∈ {red, yellow, green, None} 时对应灯 ROI 画亮色圆。"""

    import cv2

    img = np.full((600, 800, 3), 40, dtype=np.uint8)
    if lit is None:
        return img
    roi = {"red": ROI_RED, "yellow": ROI_YELLOW, "green": ROI_GREEN}[lit]
    bgr = {"red": (0, 0, 255), "yellow": (0, 255, 255), "green": (0, 255, 0)}[lit]
    cx, cy = (roi[0] + roi[2]) // 2, (roi[1] + roi[3]) // 2
    cv2.circle(img, (cx, cy), 35, bgr, -1)
    return img


def blank_image() -> np.ndarray:
    return np.zeros((600, 800, 3), dtype=np.uint8)


def shapes_image() -> np.ndarray:
    """圆 + 正方 + 细长矩形 三个白色形状（task3 分类确定性输入）。"""

    import cv2

    img = np.full((600, 800, 3), 30, dtype=np.uint8)
    cv2.circle(img, (200, 300), 50, (255, 255, 255), -1)          # round
    cv2.rectangle(img, (355, 255), (445, 345), (255, 255, 255), -1)  # square
    cv2.rectangle(img, (580, 240), (620, 360), (255, 255, 255), -1)  # irregular (1:3)
    return img


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


@dataclass
class Report:
    items: list[dict[str, Any]] = field(default_factory=list)

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
            detail = i["detail"]
            if len(detail) > 120:
                detail = detail[:120] + "…"
            print(f"  [{mark}] {i['name']:<28} {i['ms']:7.1f} ms  {detail}")
        print("=" * 64)
        print("Overall:", "PASS" if self.passed() else "FAIL")


# ---------------------------------------------------------------------------
# 服务装配
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_app(cfg_raw: dict[str, Any], captured: dict[str, Any]):
    """用 in-process mock 硬件 + 注入图像装配 aiohttp App（与生产 runner 同语义：

    业务异常**不吞**，让 server 层统一转 success=false）。"""

    from algorithm_service.config import from_dict
    from algorithm_service.server import app_factory, TaskRunner
    from algorithm_service.tasks import task1, task2, task3

    cfg = from_dict(cfg_raw)
    arm = MockArm()
    hand = MockHand()

    def capture() -> dict[str, Any]:
        return captured

    async def _t1(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, task1.run, arm, hand, cfg, capture)
        return {"lit_lamp": res.lit_lamp, "actions": res.actions}

    async def _t2(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        placed = await loop.run_in_executor(None, task2.run, arm, hand, cfg, capture)
        return {"placed": [(b.block_id, b.digit) for b in placed]}

    async def _t3(_: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, task3.run, arm, hand, cfg, capture)
        return {"placed": res.placed, "skipped": res.skipped}

    runner = TaskRunner(task1=_t1, task2=_t2, task3=_t3)
    app = app_factory(runner, ROOT / "config" / "site.yaml")
    return app, arm, hand


async def _start(app) -> tuple[Any, int]:
    from aiohttp import web

    runner_http = web.AppRunner(app)
    await runner_http.setup()
    port = _free_port()
    await web.TCPSite(runner_http, "127.0.0.1", port).start()
    return runner_http, port


# ---------------------------------------------------------------------------
# 自检流程
# ---------------------------------------------------------------------------


async def main_async(args: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    import aiohttp

    report = Report()
    captured: dict[str, Any] = {"color": blank_image(), "depth": None}
    app, arm, hand = build_app(MOCK_CFG_RAW, captured)
    runner_http, port = await _start(app)
    base = f"http://127.0.0.1:{port}"
    LOG.warning("主自检服务：%s", base)

    async with aiohttp.ClientSession() as sess:
        async def call(name: str, method: str, path: str) -> dict[str, Any]:
            t0 = time.perf_counter()
            try:
                if method == "GET":
                    ctx = sess.get(f"{base}{path}", timeout=aiohttp.ClientTimeout(total=10))
                else:
                    ctx = sess.post(f"{base}{path}", json={}, timeout=aiohttp.ClientTimeout(total=60))
                async with ctx as r:
                    body = await r.json()
                    ms = (time.perf_counter() - t0) * 1000
                    return {"ok_http": r.status == 200, "body": body, "ms": ms}
            except Exception as e:  # noqa: BLE001
                return {"ok_http": False, "body": {}, "ms": (time.perf_counter() - t0) * 1000,
                        "exception": str(e)}

        def expect(name: str, res: dict[str, Any], *, success: bool,
                   msg_has: str = "", extra: str = "") -> None:
            body = res["body"]
            ok = (
                res["ok_http"]
                and isinstance(body, dict)
                and body.get("success") is success
                and (not msg_has or msg_has in str(body.get("message", "")))
            )
            detail = json.dumps(body, ensure_ascii=False)
            if extra:
                detail += f" | {extra}"
            if res.get("exception"):
                detail += f" | EXC {res['exception']}"
            report.add(name, ok, res["ms"], detail)

        # 1. health
        expect("health", await call("health", "GET", "/api/health"), success=True, msg_has="ready")

        # 2. task1 亮红灯 → push 序列
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = panel_image("red")
        res = await call("task1", "POST", "/api/task1/execute")
        push_ok = (
            arm.visited(SW_RED["x"], SW_RED["y"] + 0.05, SW_RED["z"])      # 接近点
            and arm.visited(SW_RED["x"], SW_RED["y"] - 0.005, SW_RED["z"])  # 压入点
            and "tap" in hand.poses and hand.poses[-1] == "open"
        )
        expect("task1 红灯→push", res, success=True, msg_has="task1 ok",
               extra=f"动作链={'OK' if push_ok else 'BAD'} calls={arm.calls} poses={hand.poses}")
        report.items[-1]["ok"] = report.items[-1]["ok"] and push_ok

        # 3. task1 亮绿灯 → toggle 序列
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = panel_image("green")
        res = await call("task1", "POST", "/api/task1/execute")
        toggle_ok = (
            arm.visited(SW_TOGGLE["x"], SW_TOGGLE["y"], SW_TOGGLE["z"] + 0.05)  # 接近点
            and arm.visited(SW_TOGGLE["x"], SW_TOGGLE["y"], SW_TOGGLE["z"])     # 接触点
            and arm.visited(SW_TOGGLE["x"], SW_TOGGLE["y"], SW_TOGGLE["z"] - 0.02)  # 拨动终点
            and "flick" in hand.poses and hand.poses[-1] == "open"
        )
        expect("task1 绿灯→toggle", res, success=True, msg_has="task1 ok",
               extra=f"动作链={'OK' if toggle_ok else 'BAD'} calls={arm.calls} poses={hand.poses}")
        report.items[-1]["ok"] = report.items[-1]["ok"] and toggle_ok

        # 4. task1 无灯亮 → 明确失败，且失败后撤回了安全位（清单 5.8/8.6）
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = panel_image(None)
        res = await call("task1", "POST", "/api/task1/execute")
        retreat1 = arm.calls and arm.calls[-1] == (0.275, 0.0, 0.48)
        expect("task1 无灯→失败", res, success=False, msg_has="未检测到亮灯",
               extra=f"失败后撤回={'OK' if retreat1 else 'BAD'}")
        report.items[-1]["ok"] = report.items[-1]["ok"] and bool(retreat1)

        # 5. task2 空图 → 明确失败（旧假绿灯场景），且失败后撤回了安全位
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = blank_image()
        res = await call("task2", "POST", "/api/task2/execute")
        retreat2 = arm.calls.count((0.275, 0.0, 0.48)) >= 2  # 开场一次 + 失败撤回一次
        expect("task2 空图→失败", res, success=False, msg_has="digit recognition failed",
               extra=f"失败后撤回={'OK' if retreat2 else 'BAD'}")
        report.items[-1]["ok"] = report.items[-1]["ok"] and retreat2

        # 6. task3 三形状 → 全部入槽
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = shapes_image()
        res = await call("task3", "POST", "/api/task3/execute")
        placed = res["body"].get("message", "")
        slots_ok = (
            arm.visited(0.30, -0.25, 0.45)   # round_slot_1
            and arm.visited(0.34, -0.25, 0.45)  # square_slot_1
            and arm.visited(0.38, -0.25, 0.45)  # irregular_slot_1
            and hand.poses.count("grasp_shape") == 3
        )
        expect("task3 三形状→入槽", res, success=True, msg_has="task3 ok",
               extra=f"槽位={'OK' if slots_ok else 'BAD'} msg={placed}")
        report.items[-1]["ok"] = report.items[-1]["ok"] and slots_ok

        # 7. task3 空图 → 明确失败
        captured["color"] = blank_image()
        expect("task3 空图→失败", await call("task3", "POST", "/api/task3/execute"),
               success=False, msg_has="shape recognition failed")

    await runner_http.cleanup()

    # 8. 全占位配置：必须清晰报"未标定/未配置"，绝不裸抛 ValueError
    captured2: dict[str, Any] = {"color": shapes_image(), "depth": None}
    app2, _, _ = build_app({}, captured2)
    runner2, port2 = await _start(app2)
    base2 = f"http://127.0.0.1:{port2}"
    async with aiohttp.ClientSession() as sess2:
        t0 = time.perf_counter()
        async with sess2.post(f"{base2}/api/task1/execute", json={}, timeout=aiohttp.ClientTimeout(total=30)) as r:
            body1 = await r.json()
        ok1 = body1.get("success") is False and "panel.lamps 未配置" in str(body1.get("message", ""))
        report.add("占位配置 task1→拒动", ok1, (time.perf_counter() - t0) * 1000,
                   json.dumps(body1, ensure_ascii=False))

        t0 = time.perf_counter()
        async with sess2.post(f"{base2}/api/task3/execute", json={}, timeout=aiohttp.ClientTimeout(total=30)) as r:
            body3 = await r.json()
        msg3 = str(body3.get("message", ""))
        ok3 = (
            body3.get("success") is False
            and "未标定" in msg3
            and "could not convert" not in msg3  # 裸 ValueError 回归断言
        )
        report.add("占位配置 task3→清晰报错", ok3, (time.perf_counter() - t0) * 1000,
                   json.dumps(body3, ensure_ascii=False))
    await runner2.cleanup()

    # 9. 并发互斥：慢任务执行中再发同题 → busy
    from algorithm_service.server import TaskRunner as _TR, app_factory as _af

    class _SlowTask:
        async def __call__(self, _):
            await asyncio.sleep(0.8)
            return {"slow": True}

    slow_app = _af(_TR(task1=_SlowTask(), task2=_SlowTask(), task3=_SlowTask()),
                   ROOT / "config" / "site.yaml")
    runner3, port3 = await _start(slow_app)
    base3 = f"http://127.0.0.1:{port3}"
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as sess3:
            async def _go():
                t1 = asyncio.create_task(sess3.post(f"{base3}/api/task1/execute", json={}))
                await asyncio.sleep(0.05)  # 让第一个先抢到锁
                t2 = asyncio.create_task(sess3.post(f"{base3}/api/task1/execute", json={}))
                r1, r2 = await t1, await t2
                return await r1.json(), await r2.json()
            b1, b2 = await asyncio.wait_for(_go(), timeout=5)
        ok = (b1.get("message") == "busy" or b2.get("message") == "busy")
        report.add("并发互斥 busy", ok, (time.perf_counter() - t0) * 1000, f"r1={b1} r2={b2}")
    except Exception as e:  # noqa: BLE001
        report.add("并发互斥 busy", False, (time.perf_counter() - t0) * 1000, str(e))
    finally:
        await runner3.cleanup()

    report.print()
    return 0 if report.passed() else 1


def main() -> int:
    return asyncio.run(main_async(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
