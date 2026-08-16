"""hand_client 离线测试：stdlib 假 O10 服务验证客户端解析与报错路径。

运行：python test_hand_client_offline.py（不需要真机/第三方服务）
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hand_client import HandClient, HandError


class MockO10(BaseHTTPRequestHandler):
    error_codes = [0] * 10  # 类级状态，测试可改

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self._send({"connected": True, "hand_type": "right", "name": "omnihand_o10",
                        "model": "OmniHand 2025", "dof": 10, "position": [0.5] * 10,
                        "error_codes": list(type(self).error_codes)})
        elif self.path == "/api/pose":
            self._send({"success": True, "position": [0.5] * 10})
        elif self.path == "/api/errors":
            self._send({"success": True, "error_codes": list(type(self).error_codes)})
        else:
            self._send({"success": False, "message": "unknown"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/set_pos":
            pos = body.get("position")
            if not isinstance(pos, list) or len(pos) != 10:
                self._send({"success": False, "message": f"需要 10 个值 (0-1), 实际收到 {len(pos or [])}"}, 400)
            elif any(not (0.0 <= float(x) <= 1.0) for x in pos):
                self._send({"success": False, "message": "所有值必须在 [0, 1] 范围内"}, 400)
            else:
                self._send({"success": True, "message": "位置设置成功", "target": pos})
        elif self.path == "/api/set_pvc":
            self._send({"success": True, "message": "PVC 设置成功"})
        else:
            self._send({"success": False, "message": "unknown"}, 404)

    def log_message(self, *a) -> None:
        pass


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockO10)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    hand = HandClient(host="127.0.0.1", port=port, hand_type="right")

    passed = 0

    def ok(name: str, cond: bool, extra: str = "") -> None:
        nonlocal passed
        assert cond, f"FAIL {name} {extra}"
        passed += 1
        print(f"PASS {name} {extra}")

    ok("status", hand.status().get("connected") is True)
    ok("pose", hand.pose() == [0.5] * 10)
    ok("errors 全 0", hand.errors() == [0] * 10)

    # 正常控制
    r = hand.set_pos([1.0] * 10)
    ok("set_pos 成功", r.get("success") is True)

    # 客户端侧校验
    try:
        hand.set_pos([0.5] * 5)
        raise SystemExit("FAIL: 非 10 维未拒绝")
    except ValueError:
        ok("set_pos 非 10 维拒绝", True)
    try:
        hand.set_pos([1.5] * 10)
        raise SystemExit("FAIL: 越界值未拒绝")
    except ValueError:
        ok("set_pos 越界拒绝", True)

    # pose_name 手型表
    table = {"open": [1.0] * 10, "close": [0.0] * 10}
    ok("pose_name", hand.pose_name("open", table).get("success") is True)
    try:
        hand.pose_name("nope", table)
        raise SystemExit("FAIL: 未知手型未拒绝")
    except ValueError:
        ok("未知手型拒绝", True)

    # 错误监控：把关节 2 置为堵转，watcher 应立即触发
    MockO10.error_codes = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
    fired = []
    with hand.errors_watch(interval_s=0.05, on_error=lambda codes: fired.append(codes)):
        deadline = time.time() + 2.0
        while not fired and time.time() < deadline:
            time.sleep(0.02)
    ok("errors_watch 触发", bool(fired) and fired[0][2] == 1, str(fired[:1]))
    MockO10.error_codes = [0] * 10

    srv.shutdown()
    print(f"\n全部 {passed} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
