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
4. task1 无灯亮 → success=false，message 含"未检测到亮灯"，且失败后撤回安全位。
5. task2 空图 → success=false，message 含"digit recognition failed"，且失败后撤回。
6. task2 四数字合成图 → success=true，严格按 1→2→3→4 全入槽（真实 OCR 正路径）。
7. task3 四种形状合成图（三棱柱/正六棱柱/长方体/圆柱体） → success=true，placed=4，臂到过 4 个槽位。
8. task3 单块放置失败 → success=true 且 failed 列出该块（7.7 继续分拣）。
9. task3 灵巧手错误码非 0 → success=false，message 含"错误码"（8.4）。
10. task3 空图 → success=false，message 含"shape recognition failed"。
11. task3 形状名与 kinds 对不上 → 全跳过也 success=false（A1 防线）。
12. 全占位配置（未标定）：task1 → "panel.lamps 未配置"；task2 → "expected_count 未标定"
    （A3 防线，数量校验不得失效）；task3 → "未标定"（且绝不是裸 ValueError）。
13. 并发互斥：执行中再发同题 → 第二个拿到 busy。
14. 单元级（第四轮修复落盘，直接调 task/planner 不走 HTTP）：
    task2 重拍选帧 3 种（恰够 expected 优先 / 更接近当选 / 打平保留首帧）、
    safe_home 2 种（半标定报轴名 / 全占位回退默认）、报错文案 2 种
    （重拍失败标注"已重拍一次" / 数量校验提示不写死块数）。
15. 单元级（B3 手眼链落盘）：t_base_end @ t_end_camera 全链数学（_coords 与
    Vision 两条路径）、缺 t_base_end 拒算，共 3 种。
16. 调试端点（A1/A2/B3）：GET / 探活、/api/config/summary 未标定清单、
    每次任务请求落 JSONL（含 elapsed_ms/result_message）。
17. 单元级（2026-08-18 审查修复落盘）：无深度图生产链拒动、placement_order_target
    拼错归正、unknown 置信门禁、手型占位拒动、手眼矩阵末行非法拒算，共 5 种。

用法：``python -m tools.service_selftest``，失败 exit 1。
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
import time
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
    """模拟右臂：所有 line_to 只记录坐标，不发 HTTP；``fail_on`` 里的坐标抛 ArmError。"""

    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float]] = []
        self.fail_on: set[tuple[float, float, float]] = set()
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
        from algorithm_service.hardware import ArmError

        if any(abs(x - fx) < 1e-6 and abs(y - fy) < 1e-6 and abs(z - fz) < 1e-6
               for fx, fy, fz in self.fail_on):
            raise ArmError(f"mock 注入失败 @({x}, {y}, {z})")
        self.calls.append((x, y, z))
        return {"success": True, "message": "Cartesian execution finished for right_arm"}

    def visited(self, x: float, y: float, z: float, tol: float = 1e-6) -> bool:
        return any(
            abs(cx - x) < tol and abs(cy - y) < tol and abs(cz - z) < tol
            for cx, cy, cz in self.calls
        )


class _MockWatcher:
    """模拟 errors_watch：__enter__ 时把 inject_error 灌进 first_error。"""

    def __init__(self, hand: "MockHand") -> None:
        self._hand = hand
        self.first_error: list[int] | None = None

    def __enter__(self) -> "_MockWatcher":
        self.first_error = self._hand.inject_error
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class MockHand:
    def __init__(self) -> None:
        self.poses: list[str] = []
        self.errors_code = [0] * 10
        self.inject_error: list[int] | None = None

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
        return _MockWatcher(self)


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
            {"name": "triangular_prism", "slots": [
                {"name": "triangular_prism_slot_1", "pos": {"x": 0.30, "y": -0.25, "z": 0.45}},
            ]},
            {"name": "hexagonal_prism", "slots": [
                {"name": "hexagonal_prism_slot_1", "pos": {"x": 0.32, "y": -0.25, "z": 0.45}},
            ]},
            {"name": "rectangular_prism", "slots": [
                {"name": "rectangular_prism_slot_1", "pos": {"x": 0.34, "y": -0.25, "z": 0.45}},
            ]},
            {"name": "cylinder", "slots": [
                {"name": "cylinder_slot_1", "pos": {"x": 0.36, "y": -0.25, "z": 0.45}},
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
    """三棱柱 + 正六棱柱 + 长方体 + 圆柱体 四个白色形状（task3 分类确定性输入）。

    各形状画法经整合管线实测分类稳定（六边形旋转 15° 使其 fill_ratio 落入
    六棱柱分支；圆/三角/矩形常规画法即可）。
    """

    import cv2

    img = np.full((600, 800, 3), 30, dtype=np.uint8)
    cv2.circle(img, (150, 300), 70, (255, 255, 255), -1)               # cylinder
    tri = np.array([[[330, 240]], [[390, 360]], [[270, 360]]], dtype=np.int32)
    cv2.fillPoly(img, [tri], (255, 255, 255))                          # triangular_prism
    hexpts = cv2.ellipse2Poly((540, 300), (52, 52), 15, 0, 360, 60).reshape(-1, 1, 2)
    cv2.fillPoly(img, [hexpts], (255, 255, 255))                       # hexagonal_prism
    cv2.rectangle(img, (660, 250), (700, 350), (255, 255, 255), -1)    # rectangular_prism
    return img


def pentagon_image() -> np.ndarray:
    """正五边形（四分类外的未知物）：应被置信门禁全部拦下。"""

    import cv2

    img = np.full((600, 800, 3), 30, dtype=np.uint8)
    pent = cv2.ellipse2Poly((400, 300), (80, 80), 0, 0, 360, 72).reshape(-1, 1, 2)
    cv2.fillPoly(img, [pent], (255, 255, 255))
    return img


def digits_image() -> np.ndarray:
    """4 个带数字的白色长方块（task2 OCR 确定性输入，本机 tesseract 已验证）。"""

    import cv2

    img = np.zeros((600, 800, 3), dtype=np.uint8)
    positions = [(150, 150), (400, 150), (150, 420), (400, 420)]
    for i, (cx, cy) in enumerate(positions, start=1):
        cv2.rectangle(img, (cx - 55, cy - 40), (cx + 55, cy + 40), (255, 255, 255), -1)
        cv2.putText(img, str(i), (cx - 18, cy + 22), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 5)
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
        return {"placed": res.placed, "skipped": res.skipped, "failed": res.failed}

    runner = TaskRunner(task1=_t1, task2=_t2, task3=_t3)
    app = app_factory(runner, ROOT / "config" / "site.yaml", cfg)
    return app, arm, hand


async def _start(app) -> tuple[Any, int]:
    from aiohttp import web

    runner_http = web.AppRunner(app)
    await runner_http.setup()
    port = _free_port()
    await web.TCPSite(runner_http, "127.0.0.1", port).start()
    return runner_http, port


# ---------------------------------------------------------------------------
# 单元级场景（第四轮修复的回归防线，直接调 task/planner，不走 HTTP）
# ---------------------------------------------------------------------------


def _unit_scenarios(report: Report) -> None:
    """task2 重拍选帧 3 种 + safe_home 2 种 + 报错文案 2 种。"""

    import copy

    from algorithm_service.config import PLACEHOLDER, from_dict
    from algorithm_service.planner import PickError, Pose, safe_home
    from algorithm_service.tasks import task2
    from algorithm_service.tasks.task2_vision import _Detected

    def fake_detected(n: int) -> list[Any]:
        return [_Detected(block_id=i, digit=i + 1, pick=Pose(0.25, -0.12, 0.45))
                for i in range(n)]

    seq: list[int] = []
    calls = {"n": 0}

    def fake_recognize(color: Any, depth: Any, cfg: Any, t_base_end: Any = None,
                       *, allow_staging: bool = False) -> list[Any]:
        v = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return fake_detected(v)

    def run_task2(cfg_raw: dict[str, Any] | None = None) -> list[Any]:
        cfg = from_dict(copy.deepcopy(cfg_raw or MOCK_CFG_RAW))
        img = blank_image()
        return task2.run(MockArm(), MockHand(), cfg,
                         lambda: {"color": img, "depth": None, "allow_staging": True})

    def scenario(name: str, fn: Any) -> None:
        t0 = time.perf_counter()
        try:
            detail = fn()
            report.add(name, True, (time.perf_counter() - t0) * 1000, str(detail))
        except Exception as e:  # noqa: BLE001
            report.add(name, False, (time.perf_counter() - t0) * 1000,
                       f"{type(e).__name__}: {e}")

    orig = task2.recognize_digits
    task2.recognize_digits = fake_recognize
    try:
        def s_exact() -> str:
            seq[:] = [5, 4]
            calls["n"] = 0
            placed = run_task2()
            assert len(placed) == 4, f"应放 4 块，实际 {len(placed)}"
            return "首帧误检 5 个被丢弃，重拍恰够 4 个全入槽"

        def s_closer() -> str:
            seq[:] = [2, 3]
            calls["n"] = 0
            try:
                run_task2()
            except PickError as e:
                assert "got 3" in str(e), f"报错数字错: {e}"
                return str(e)
            raise AssertionError("数量不足应失败")

        def s_tie() -> str:
            seq[:] = [5, 3]
            calls["n"] = 0
            try:
                run_task2()
            except PickError as e:
                assert "got 5" in str(e), f"报错数字错: {e}"
                return str(e)
            raise AssertionError("数量不对应失败")

        scenario("重拍选帧-恰够 expected 优先", s_exact)
        scenario("重拍选帧-更接近当选", s_closer)
        scenario("重拍选帧-打平保留首帧", s_tie)

        def s_msg_retry() -> str:
            seq[:] = [1, 2]
            calls["n"] = 0
            try:
                run_task2()
            except PickError as e:
                assert "got 2" in str(e) and "已重拍一次" in str(e), str(e)
                return str(e)
            raise AssertionError("数量不足应失败")

        def s_msg_count() -> str:
            raw = copy.deepcopy(MOCK_CFG_RAW)
            raw["digit_blocks"]["expected_count"] = PLACEHOLDER
            try:
                run_task2(raw)
            except PickError as e:
                assert "expected_count" in str(e) and "4 块" not in str(e), str(e)
                return str(e)
            raise AssertionError("expected_count 占位应拒动")

        scenario("文案-重拍失败标注重拍", s_msg_retry)
        scenario("文案-数量校验不写死块数", s_msg_count)
    finally:
        task2.recognize_digits = orig

    def s_partial_home() -> str:
        raw = copy.deepcopy(MOCK_CFG_RAW)
        raw["service"]["safe_home"] = {"x": 0.30}
        try:
            safe_home(MockArm(), from_dict(raw))
        except PickError as e:
            assert "service.safe_home.y" in str(e), f"没报清轴名: {e}"
            return str(e)
        raise AssertionError("半标定应抛错")

    def s_full_placeholder_home() -> str:
        raw = copy.deepcopy(MOCK_CFG_RAW)
        raw["service"]["safe_home"] = {"x": PLACEHOLDER, "y": PLACEHOLDER, "z": PLACEHOLDER}
        arm = MockArm()
        safe_home(arm, from_dict(raw))
        assert arm.visited(0.275, 0.0, 0.48), arm.calls
        return "回退内置默认位 (0.275, 0, 0.48)"

    scenario("safe_home 半标定→报轴名", s_partial_home)
    scenario("safe_home 全占位→回退默认", s_full_placeholder_home)

    # 像素链（B3 防线）：t_base_end @ t_end_camera 全链数学 + 缺任一环拒算
    from algorithm_service.tasks._coords import pixel_to_base_pose, xyzrpy_to_matrix
    from algorithm_service.vision import Vision, VisionError

    def s_chain() -> str:
        cfg = from_dict(copy.deepcopy(MOCK_CFG_RAW))  # 内参 600/600/400/300，hand_eye=单位阵
        t_be = xyzrpy_to_matrix({"x": 0.5, "y": 0.1, "z": 0.3, "roll": 0, "pitch": 0, "yaw": 0})
        p = pixel_to_base_pose(400, 300, 1.0, cfg, t_be)  # 中心像素 → 相机正前方 1m
        assert abs(p.x - 0.5) < 1e-9 and abs(p.y - 0.1) < 1e-9 and abs(p.z - 1.3) < 1e-9, p
        return f"t_base_end 平移正确叠加 → ({p.x}, {p.y}, {p.z})"

    def s_chain_missing() -> str:
        cfg = from_dict(copy.deepcopy(MOCK_CFG_RAW))
        try:
            pixel_to_base_pose(400, 300, 1.0, cfg, None)
        except PickError as e:
            assert "t_base_end" in str(e), str(e)
            return str(e)
        raise AssertionError("缺 t_base_end 应拒算")

    def s_chain_vision() -> str:
        identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        v = Vision(intrinsics=(600, 600, 400, 300), hand_eye=identity)
        try:
            try:
                v.pixel_to_base(400, 300, 1.0)
                raise AssertionError("Vision 缺 t_base_end 应拒算")
            except VisionError as e:
                assert "t_base_end" in str(e), str(e)
            t_be = xyzrpy_to_matrix({"x": 0.5, "y": 0.1, "z": 0.3, "roll": 0, "pitch": 0, "yaw": 0})
            x, y, z = v.pixel_to_base(400, 300, 1.0, t_be)
            assert abs(x - 0.5) < 1e-9 and abs(y - 0.1) < 1e-9 and abs(z - 1.3) < 1e-9, (x, y, z)
            return f"Vision.pixel_to_base 同链 → ({x:.3f}, {y:.3f}, {z:.3f})"
        finally:
            v.close()

    scenario("像素链-t_base_end 合成", s_chain)
    scenario("像素链-缺位姿拒算", s_chain_missing)
    scenario("像素链-Vision 同款", s_chain_vision)

    # ---- 第五轮修复（审查报告 2026-08-18）的回归防线 ---------------------

    from algorithm_service.tasks import task3

    def s_no_depth_refused() -> str:
        # 生产链路（无 allow_staging 注入）+ 无深度图 → 必须拒动，
        # 绝不静默回退 staging 让 4 个块挤同一坐标还报 success
        cfg = from_dict(copy.deepcopy(MOCK_CFG_RAW))
        try:
            task2.run(MockArm(), MockHand(), cfg,
                      lambda: {"color": digits_image(), "depth": None})
        except PickError as e:
            assert "无深度图" in str(e), str(e)
            return str(e)
        raise AssertionError("无深度图且未显式 allow_staging 应拒动")

    def s_desending_typo() -> str:
        # placement_order_target 拼错（"desending"）→ 告警并归正 ascending，绝不静默反序
        seq[:] = [4]
        calls["n"] = 0
        task2.recognize_digits = fake_recognize
        try:
            raw = copy.deepcopy(MOCK_CFG_RAW)
            raw["digit_blocks"]["placement_order_target"] = "desending"
            placed = run_task2(raw)
        finally:
            task2.recognize_digits = orig
        digits = [b.digit for b in placed]
        assert digits == [1, 2, 3, 4], f"拼错归正后仍应升序，实际 {digits}"
        return f"desending 拼错 → 归正 ascending，落槽序={digits}"

    def s_unknown_gated() -> str:
        # 五边形（四分类外的物体）→ unknown 置信门禁全拦 → 任务明确失败而非放错槽
        cfg = from_dict(copy.deepcopy(MOCK_CFG_RAW))
        try:
            task3.run(MockArm(), MockHand(), cfg,
                      lambda: {"color": pentagon_image(), "depth": None, "allow_staging": True})
        except PickError as e:
            assert "shape recognition failed" in str(e), str(e)
            return str(e)
        raise AssertionError("unknown 全被门禁拦下时应明确失败")

    def s_hand_pose_placeholder() -> str:
        # 手型占位 → 拒动指名（占位符防线覆盖 hand.poses，不静默用全 0 握拳上场）
        raw = copy.deepcopy(MOCK_CFG_RAW)
        raw["hand"]["poses"]["grasp_digit"] = [PLACEHOLDER] * 10
        cfg = from_dict(raw)
        try:
            task2.run(MockArm(), MockHand(), cfg,
                      lambda: {"color": digits_image(), "depth": None, "allow_staging": True})
        except PickError as e:
            assert "手型未标定" in str(e) and "grasp_digit" in str(e), str(e)
            return str(e)
        raise AssertionError("手型占位应拒动")

    def s_handeye_bad_last_row() -> str:
        # 手眼矩阵填错半截（末行不是 [0,0,0,1]）→ 拒算（旧版只查 he[0][0] 会放行）
        raw = copy.deepcopy(MOCK_CFG_RAW)
        raw["hand_eye"]["rows"] = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 0.5]]
        cfg = from_dict(raw)
        t_be = xyzrpy_to_matrix({"x": 0.5, "y": 0.1, "z": 0.3, "roll": 0, "pitch": 0, "yaw": 0})
        try:
            pixel_to_base_pose(400, 300, 1.0, cfg, t_be)
        except PickError as e:
            assert "末行" in str(e), str(e)
            return str(e)
        raise AssertionError("手眼末行非法应拒算")

    scenario("无深度图→拒动(生产链)", s_no_depth_refused)
    scenario("order 拼错→归正告警", s_desending_typo)
    scenario("unknown 置信门禁", s_unknown_gated)
    scenario("手型占位→拒动指名", s_hand_pose_placeholder)
    scenario("手眼末行非法→拒算", s_handeye_bad_last_row)


# ---------------------------------------------------------------------------
# 自检流程
# ---------------------------------------------------------------------------


async def main_async(args: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    import aiohttp

    report = Report()
    # allow_staging=True：显式声明本帧来自自检 mock，无深度图时允许回退 staging 坐标
    #（生产 capture 永远不带这个键——无深度图会被 task2/3 直接 PickError 拒动）
    captured: dict[str, Any] = {"color": blank_image(), "depth": None, "allow_staging": True}
    import tempfile
    log_tmp = tempfile.mkdtemp(prefix="selftest_logs_")
    MOCK_CFG_RAW["service"]["log_dir"] = log_tmp  # JSONL 落盘场景用临时目录，别污染仓库
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
                   msg_has: str = "", extra_ok: bool = True, extra: str = "") -> None:
            body = res["body"]
            ok = (
                res["ok_http"]
                and isinstance(body, dict)
                and body.get("success") is success
                and (not msg_has or msg_has in str(body.get("message", "")))
                and extra_ok
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
        expect("task1 红灯→push", res, success=True, msg_has="task1 ok", extra_ok=push_ok,
               extra=f"动作链={'OK' if push_ok else 'BAD'} calls={arm.calls} poses={hand.poses}")

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
        expect("task1 绿灯→toggle", res, success=True, msg_has="task1 ok", extra_ok=toggle_ok,
               extra=f"动作链={'OK' if toggle_ok else 'BAD'} calls={arm.calls} poses={hand.poses}")

        # 4. task1 无灯亮 → 明确失败，且失败后撤回了安全位（清单 5.8/8.6）
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = panel_image(None)
        res = await call("task1", "POST", "/api/task1/execute")
        retreat1 = arm.calls and arm.calls[-1] == (0.275, 0.0, 0.48)
        expect("task1 无灯→失败", res, success=False, msg_has="未检测到亮灯",
               extra_ok=bool(retreat1), extra=f"失败后撤回={'OK' if retreat1 else 'BAD'}")

        # 5. task2 空图 → 明确失败（旧假绿灯场景），且失败后撤回了安全位
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = blank_image()
        res = await call("task2", "POST", "/api/task2/execute")
        retreat2 = arm.calls.count((0.275, 0.0, 0.48)) >= 2  # 开场一次 + 失败撤回一次
        expect("task2 空图→失败", res, success=False, msg_has="digit recognition failed",
               extra_ok=retreat2, extra=f"失败后撤回={'OK' if retreat2 else 'BAD'}")

        # 5b. task2 四数字 → 严格按 1→2→3→4 全部入槽（正路径，断言槽位访问顺序）
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = digits_image()
        res = await call("task2", "POST", "/api/task2/execute")
        slot_coords = [(0.30 + 0.02 * i, -0.25, 0.45) for i in range(4)]
        first_visit = [
            next((k for k, c in enumerate(arm.calls)
                  if abs(c[0] - sx) < 1e-6 and abs(c[1] - sy) < 1e-6 and abs(c[2] - sz) < 1e-6),
                 None)
            for sx, sy, sz in slot_coords
        ]
        t2_ok = (
            all(v is not None for v in first_visit)
            and first_visit == sorted(first_visit)  # 严格按 slot_1→2→3→4 顺序到访
            and hand.poses.count("grasp_digit") == 4
        )
        expect("task2 四数字→按序入槽", res, success=True, msg_has="task2 ok", extra_ok=t2_ok,
               extra=f"槽位/手型={'OK' if t2_ok else 'BAD'} 首访序={first_visit} msg={res['body'].get('message', '')}")

        # 6. task3 四形状 → 全部入槽
        arm.calls.clear(); hand.poses.clear()
        captured["color"] = shapes_image()
        res = await call("task3", "POST", "/api/task3/execute")
        placed = res["body"].get("message", "")
        slots_ok = (
            arm.visited(0.30, -0.25, 0.45)   # triangular_prism_slot_1
            and arm.visited(0.32, -0.25, 0.45)  # hexagonal_prism_slot_1
            and arm.visited(0.34, -0.25, 0.45)  # rectangular_prism_slot_1
            and arm.visited(0.36, -0.25, 0.45)  # cylinder_slot_1
            and hand.poses.count("grasp_shape") == 4
        )
        expect("task3 四形状→入槽", res, success=True, msg_has="task3 ok", extra_ok=slots_ok,
               extra=f"槽位={'OK' if slots_ok else 'BAD'} msg={placed}")

        # 6b. task3 单块失败不中止（7.7）：rectangular_prism 槽位注入失败 → 其余三块照常入槽
        arm.calls.clear(); hand.poses.clear()
        arm.fail_on = {(0.34, -0.25, 0.45)}  # rectangular_prism_slot_1
        captured["color"] = shapes_image()
        res = await call("task3", "POST", "/api/task3/execute")
        arm.fail_on = set()
        msg6b = str(res["body"].get("message", ""))
        partial_ok = (
            arm.visited(0.30, -0.25, 0.45)      # triangular_prism 照常
            and arm.visited(0.32, -0.25, 0.45)  # hexagonal_prism 照常
            and arm.visited(0.36, -0.25, 0.45)  # cylinder 照常
            and '"failed"' in msg6b and "rectangular_prism" in msg6b
        )
        expect("task3 单块失败→继续", res, success=True, msg_has="task3 ok", extra_ok=partial_ok,
               extra=f"部分完成={'OK' if partial_ok else 'BAD'} msg={msg6b}")

        # 6c. 灵巧手错误码非 0 → 立即中止（8.4），不得假成功
        hand.inject_error = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        captured["color"] = shapes_image()
        res = await call("task3", "POST", "/api/task3/execute")
        hand.inject_error = None
        expect("task3 手错误→中止", res, success=False, msg_has="错误码")

        # 7. task3 空图 → 明确失败
        captured["color"] = blank_image()
        expect("task3 空图→失败", await call("task3", "POST", "/api/task3/execute"),
               success=False, msg_has="shape recognition failed")

        # 7c. 调试端点：GET / 探活 + /api/config/summary 未标定清单
        expect("GET / 根路由", await call("root", "GET", "/"), success=True, msg_has="ready")
        import copy

        cfg_ph = copy.deepcopy(MOCK_CFG_RAW)
        cfg_ph["camera"] = {k: "__现场标定后填入__" for k in ("fx", "fy", "cx", "cy")}
        app_ph, _, _ = build_app(cfg_ph, {"color": blank_image(), "depth": None})
        runner_ph, port_ph = await _start(app_ph)
        try:
            async with aiohttp.ClientSession() as sess_ph:
                t0 = time.perf_counter()
                async with sess_ph.get(
                    f"http://127.0.0.1:{port_ph}/api/config/summary",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    body_sum = await r.json()
            uncal = body_sum.get("uncalibrated", [])
            ok_sum = (
                body_sum.get("success") is True
                and "camera.fx" in uncal
                and body_sum.get("dryRun") is False
            )
            report.add("summary-未标定清单", ok_sum, (time.perf_counter() - t0) * 1000,
                       f"未标定 {len(uncal)} 项 dryRun={body_sum.get('dryRun')}")
        finally:
            await runner_ph.cleanup()

        # 7d. JSONL 请求日志落盘（上面跑过的 task 调用都应留有记录）
        log_files = list(Path(log_tmp).glob("*.jsonl"))
        ok_log = False
        detail_log = "无文件"
        if log_files:
            lines = log_files[0].read_text(encoding="utf-8").strip().splitlines()
            ok_log = any(json.loads(line).get("task") == "task2" for line in lines)
            detail_log = f"{len(lines)} 行, 含 task2={ok_log}"
        report.add("JSONL 日志落盘", ok_log, 0.0, detail_log)

    await runner_http.cleanup()

    # 7b. task3 形状名与 kinds 对不上 → 全跳过也必须 success=false（A1 防线）
    import copy

    cfg_no_kinds = copy.deepcopy(MOCK_CFG_RAW)
    cfg_no_kinds["shapes"]["kinds"] = []
    captured3: dict[str, Any] = {"color": shapes_image(), "depth": None, "allow_staging": True}
    app3, _, _ = build_app(cfg_no_kinds, captured3)
    runner3b, port3b = await _start(app3)
    base3b = f"http://127.0.0.1:{port3b}"
    async with aiohttp.ClientSession() as sess3b:
        t0 = time.perf_counter()
        async with sess3b.post(f"{base3b}/api/task3/execute", json={}, timeout=aiohttp.ClientTimeout(total=30)) as r:
            body_sk = await r.json()
        ok_sk = body_sk.get("success") is False and "都没放入槽" in str(body_sk.get("message", ""))
        report.add("task3 全跳过→失败(A1)", ok_sk, (time.perf_counter() - t0) * 1000,
                   json.dumps(body_sk, ensure_ascii=False))
    await runner3b.cleanup()

    # 8. 全占位配置：必须清晰报"未标定/未配置"，绝不裸抛 ValueError
    captured2: dict[str, Any] = {"color": shapes_image(), "depth": None, "allow_staging": True}
    app2, _, _ = build_app({"service": {"log_dir": log_tmp}}, captured2)
    runner2, port2 = await _start(app2)
    base2 = f"http://127.0.0.1:{port2}"
    async with aiohttp.ClientSession() as sess2:
        t0 = time.perf_counter()
        async with sess2.post(f"{base2}/api/task1/execute", json={}, timeout=aiohttp.ClientTimeout(total=30)) as r:
            body1 = await r.json()
        ok1 = body1.get("success") is False and "panel.lamps 未配置" in str(body1.get("message", ""))
        report.add("占位配置 task1→拒动", ok1, (time.perf_counter() - t0) * 1000,
                   json.dumps(body1, ensure_ascii=False))

        # A3 防线：expected_count 占位 → 数量校验不得失效（块识别得出也拒动）
        captured2["color"] = digits_image()
        t0 = time.perf_counter()
        async with sess2.post(f"{base2}/api/task2/execute", json={}, timeout=aiohttp.ClientTimeout(total=30)) as r:
            body2 = await r.json()
        ok2 = body2.get("success") is False and "expected_count" in str(body2.get("message", ""))
        report.add("占位配置 task2→数量校验(A3)", ok2, (time.perf_counter() - t0) * 1000,
                   json.dumps(body2, ensure_ascii=False))

        captured2["color"] = shapes_image()
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

    from algorithm_service.config import from_dict as _fd

    slow_app = _af(_TR(task1=_SlowTask(), task2=_SlowTask(), task3=_SlowTask()),
                   ROOT / "config" / "site.yaml",
                   _fd({"service": {"log_dir": log_tmp}}))
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

    _unit_scenarios(report)

    report.print()
    return 0 if report.passed() else 1


def main() -> int:
    return asyncio.run(main_async(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
