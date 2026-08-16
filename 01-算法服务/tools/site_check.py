"""``tools/site_check.py`` —— 标定日 30 秒汇总自检。

一次跑完看汇总，不用翻四个模块：

* 机械臂：status 可达 → motors 无故障有反馈 → 使能状态
* 灵巧手：status 可达 → errors 全 0
* 相机：pyorbbecsdk 初始化 + 取一帧
* 算法服务：本机 5000 健康检查（服务没起则提示）
* site.yaml：未标定项清单 + dry_run 状态

用法：``python -m tools.site_check``（在 01-算法服务/ 下），有 ❌ 退出码 1。
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_service.config import collect_placeholders, load as load_cfg  # noqa: E402

ROWS: list[tuple[str, str, str]] = []


def _row(level: str, item: str, detail: str = "") -> None:
    ROWS.append((level, item, detail))
    print(f"  {level} {item:<16} {detail}")


def ok(item: str, detail: str = "") -> None:
    _row("✅", item, detail)


def warn(item: str, detail: str = "") -> None:
    _row("⚠️", item, detail)


def fail(item: str, detail: str = "") -> None:
    _row("❌", item, detail)


def _short(e: Exception) -> str:
    """连接类错误只留一句人话，别把堆栈糊到汇总表上。"""

    text = str(e)
    for marker in ("Max retries exceeded", "远程主机", "由于目标计算机"):
        if marker in text:
            return "连接失败（检查 IP/网线/服务是否启动）"
    return text[:120]


def main() -> int:
    cfg = load_cfg(ROOT / "config" / "site.yaml")
    svc = cfg.service

    print("== 机械臂 ==")
    try:
        from algorithm_service.hardware import ArmClient

        arm = ArmClient(host=svc.arm_host, port=svc.arm_port, side=svc.arm_side,
                        default_rpy=svc.default_rpy)
        try:
            arm.status()
            ok("臂 status", f"{svc.arm_host}:{svc.arm_port}")
            if arm.healthy():
                ok("臂 motors", "无故障且有反馈")
            else:
                fail("臂 motors", "有电机故障或无反馈")
            if arm.enabled():
                ok("臂使能", "已使能")
            else:
                warn("臂使能", "未使能（任务会自动 enable；急停拍下时会是这样）")
        except Exception as e:  # noqa: BLE001
            fail("臂 status", _short(e))
    except ImportError as e:
        fail("臂客户端", f"依赖缺失: {e}")

    print("== 灵巧手 ==")
    try:
        from algorithm_service.hardware import HandClient

        hand = HandClient(host=svc.hand_host, port=svc.hand_port, hand_type=svc.hand_type)
        try:
            hand.status()
            ok("手 status", f"{svc.hand_host}:{svc.hand_port}")
            errs = hand.errors()
            if all(v == 0 for v in errs):
                ok("手 errors", "全 0")
            else:
                fail("手 errors", f"非 0 错误码: {errs}")
        except Exception as e:  # noqa: BLE001
            fail("手 status", _short(e))
    except ImportError as e:
        fail("手客户端", f"依赖缺失: {e}")

    print("== 相机 ==")
    try:
        from algorithm_service.vision import Vision

        vision = Vision()
        try:
            frame = vision.capture(timeout_ms=2000)
            ok("相机取图", f"{frame.color.shape[1]}x{frame.color.shape[0]} "
                         f"深度={'有' if frame.depth is not None else '无'}")
        except Exception as e:  # noqa: BLE001
            fail("相机取图", str(e))
        finally:
            vision.close()
    except Exception as e:  # noqa: BLE001
        fail("相机初始化", str(e))

    print("== 算法服务（本机 5000） ==")
    try:
        with urllib.request.urlopen("http://127.0.0.1:5000/api/health", timeout=3) as r:
            import json

            body = json.loads(r.read().decode("utf-8"))
        if body.get("success"):
            ok("服务健康", "ready")
        else:
            fail("服务健康", str(body))
    except Exception:  # noqa: BLE001
        warn("服务健康", "未运行（标定阶段可先不起；上场前必须起）")

    print("== site.yaml 标定项 ==")
    missing = collect_placeholders(cfg)
    if missing:
        fail("未标定项", f"{len(missing)} 项：" + ", ".join(missing[:6]) + (" …" if len(missing) > 6 else ""))
    else:
        ok("未标定项", "全部已填")
    if svc.dry_run:
        fail("dry_run", "⚠️ DRY-RUN 开着！上场前必须改回 false")
    else:
        ok("dry_run", "false")

    return _summary()


def _summary() -> int:
    fails = sum(1 for lv, _, _ in ROWS if lv == "❌")
    warns = sum(1 for lv, _, _ in ROWS if lv == "⚠️")
    print("=" * 50)
    print(f"汇总：❌ {fails} 项，⚠️ {warns} 项，✅ {len(ROWS) - fails - warns} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
