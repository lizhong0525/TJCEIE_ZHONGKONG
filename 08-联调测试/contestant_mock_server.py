#!/usr/bin/env python3
"""中控杯选手算法服务模拟器。

默认启动全部成功的接口：
    python contestant_mock_server.py

模拟赛题 2 返回业务失败：
    python contestant_mock_server.py --task2-mode failure

模拟赛题 1 执行 8 秒：
    python contestant_mock_server.py --task1-delay 8

使用 --help 查看全部参数。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


ENDPOINT_PATHS = {
    "health": "/api/health",
    "task1": "/api/task1/execute",
    "task2": "/api/task2/execute",
    "task3": "/api/task3/execute",
}

MODE_CHOICES = ("success", "failure", "http-error", "invalid-json", "empty")
MAX_REQUEST_BODY_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    default_delay: float
    endpoint_delays: dict[str, float | None]
    endpoint_modes: dict[str, str]
    failure_message: str
    http_error_status: int

    def delay_for(self, endpoint: str) -> float:
        endpoint_delay = self.endpoint_delays[endpoint]
        return self.default_delay if endpoint_delay is None else endpoint_delay


class CallCounter:
    def __init__(self) -> None:
        self._counts = {endpoint: 0 for endpoint in ENDPOINT_PATHS}
        self._lock = threading.Lock()

    def increment(self, endpoint: str) -> int:
        with self._lock:
            self._counts[endpoint] += 1
            return self._counts[endpoint]


class ContestantMockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        config: ServerConfig,
    ) -> None:
        super().__init__(server_address, ContestantRequestHandler)
        self.config = config
        self.call_counter = CallCounter()


class ContestantRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ZhongkongCupContestantMock/1.0"

    @property
    def mock_server(self) -> ContestantMockServer:
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == ENDPOINT_PATHS["health"]:
            self._execute_endpoint("health", None)
            return

        if self.path in ENDPOINT_PATHS.values():
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"success": False, "message": "该接口不支持 GET 方法"},
            )
            return

        self._send_not_found()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        endpoint = next(
            (
                name
                for name, path in ENDPOINT_PATHS.items()
                if name != "health" and path == self.path
            ),
            None,
        )
        if endpoint is None:
            if self.path == ENDPOINT_PATHS["health"]:
                self._send_json(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    {"success": False, "message": "健康检查只支持 GET 方法"},
                )
            else:
                self._send_not_found()
            return

        request_body = self._read_json_request()
        if request_body is None:
            return

        self._execute_endpoint(endpoint, request_body)

    def _read_json_request(self) -> dict[str, Any] | None:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"success": False, "message": "Content-Type 必须是 application/json"},
            )
            return None

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"success": False, "message": "Content-Length 无效"},
            )
            return None

        if content_length > MAX_REQUEST_BODY_SIZE:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"success": False, "message": "请求体过大"},
            )
            return None

        if content_length == 0:
            # 与 01 真服务行为对齐：空 body 按 {} 处理（真服务 _read_json_or_empty
            # 对空 body 直接放行；不对齐的话 mock 阶段 400、真机阶段 200，误导排查）
            return {}

        raw_body = self.rfile.read(content_length)
        try:
            decoded_body = raw_body.decode("utf-8")
            body = json.loads(decoded_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"success": False, "message": "请求体必须是 UTF-8 编码的 JSON"},
            )
            return None

        if not isinstance(body, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"success": False, "message": "请求 JSON 的根节点必须是对象"},
            )
            return None

        print(
            f"[{now_text()}] 收到 {self.command} {self.path} "
            f"Content-Type={content_type} Body={decoded_body or '<empty>'}",
            flush=True,
        )
        return body

    def _execute_endpoint(
        self,
        endpoint: str,
        request_body: dict[str, Any] | None,
    ) -> None:
        del request_body
        config = self.mock_server.config
        call_count = self.mock_server.call_counter.increment(endpoint)
        mode = config.endpoint_modes[endpoint]
        delay = config.delay_for(endpoint)
        started_at = time.perf_counter()

        if endpoint == "health":
            print(f"[{now_text()}] 收到 GET {self.path}", flush=True)

        print(
            f"[{now_text()}] 开始处理 {endpoint}，第 {call_count} 次调用，"
            f"模式={mode}，延迟={delay:g} 秒",
            flush=True,
        )
        if delay > 0:
            time.sleep(delay)

        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        if mode == "success":
            message = "ready" if endpoint == "health" else f"{endpoint} ok"
            self._send_json(
                HTTPStatus.OK,
                {
                    "success": True,
                    "message": message,
                    "callCount": call_count,
                    "elapsedMs": elapsed_ms,
                },
            )
        elif mode == "failure":
            self._send_json(
                HTTPStatus.OK,
                {
                    "success": False,
                    "message": config.failure_message,
                    "callCount": call_count,
                },
            )
        elif mode == "http-error":
            self._send_json(
                config.http_error_status,
                {
                    "success": False,
                    "message": f"模拟 HTTP {config.http_error_status} 错误",
                },
            )
        elif mode == "invalid-json":
            self._send_bytes(HTTPStatus.OK, b"this is not valid json", "application/json")
        elif mode == "empty":
            self._send_bytes(HTTPStatus.OK, b"", "application/json; charset=utf-8")

        print(
            f"[{now_text()}] 完成 {endpoint}，第 {call_count} 次调用，耗时 {elapsed_ms} ms",
            flush=True,
        )

    def _send_not_found(self) -> None:
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"success": False, "message": f"未知接口：{self.path}"},
        )

    def _send_json(self, status: int | HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_bytes(
        self,
        status: int | HTTPStatus,
        body: bytes,
        content_type: str,
    ) -> None:
        try:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(body)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print(
                f"[{now_text()}] 客户端已停止等待，响应未能完整发送",
                flush=True,
            )

    def log_message(self, format_text: str, *args: object) -> None:
        del format_text, args


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def non_negative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("延迟不能小于 0")
    return number


def valid_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间")
    return port


def valid_http_status(value: str) -> int:
    status = int(value)
    if not 400 <= status <= 599:
        raise argparse.ArgumentTypeError("HTTP 错误状态码必须在 400 到 599 之间")
    return status


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="中控杯选手算法 HTTP 接口模拟服务",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=valid_port, default=5000, help="监听端口")
    parser.add_argument(
        "--delay",
        type=non_negative_float,
        default=0.0,
        help="全部接口的默认响应延迟（秒）",
    )
    parser.add_argument(
        "--failure-message",
        default="camera not ready",
        help="failure 模式返回的 message",
    )
    parser.add_argument(
        "--http-error-status",
        type=valid_http_status,
        default=500,
        help="http-error 模式返回的状态码",
    )

    for endpoint in ENDPOINT_PATHS:
        parser.add_argument(
            f"--{endpoint}-mode",
            choices=MODE_CHOICES,
            default="success",
            help=f"{endpoint} 接口响应模式",
        )
        parser.add_argument(
            f"--{endpoint}-delay",
            type=non_negative_float,
            default=None,
            help=f"{endpoint} 接口独立延迟（秒），未设置时使用 --delay",
        )

    return parser


def config_from_args(args: argparse.Namespace) -> ServerConfig:
    return ServerConfig(
        host=args.host,
        port=args.port,
        default_delay=args.delay,
        endpoint_delays={
            endpoint: getattr(args, f"{endpoint}_delay")
            for endpoint in ENDPOINT_PATHS
        },
        endpoint_modes={
            endpoint: getattr(args, f"{endpoint}_mode")
            for endpoint in ENDPOINT_PATHS
        },
        failure_message=args.failure_message,
        http_error_status=args.http_error_status,
    )


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def print_startup_summary(config: ServerConfig) -> None:
    base_url = f"http://{config.host}:{config.port}"
    print("=" * 64)
    print("中控杯选手算法服务模拟器已启动")
    print(f"WPF 测试工具 Base URL：{base_url}")
    print("接口：")
    print(f"  GET  {ENDPOINT_PATHS['health']}")
    for endpoint in ("task1", "task2", "task3"):
        print(f"  POST {ENDPOINT_PATHS[endpoint]}")
    print("当前响应模式：")
    for endpoint in ENDPOINT_PATHS:
        print(
            f"  {endpoint:<6} mode={config.endpoint_modes[endpoint]:<12} "
            f"delay={config.delay_for(endpoint):g}s"
        )
    print("按 Ctrl+C 停止服务")
    print("=" * 64, flush=True)


def main() -> int:
    configure_console_encoding()
    parser = build_argument_parser()
    args = parser.parse_args()
    config = config_from_args(args)

    try:
        server = ContestantMockServer((config.host, config.port), config)
    except OSError as error:
        print(
            f"启动失败：无法监听 {config.host}:{config.port}，{error}",
            file=sys.stderr,
        )
        return 1

    print_startup_summary(config)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print(f"\n[{now_text()}] 正在停止模拟服务...", flush=True)
    finally:
        server.server_close()

    print(f"[{now_text()}] 模拟服务已停止", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
