"""轻量级 pytest 基础测试：不加载模型，仅验证 /health 与异常路径。"""

import os
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app import app


SAMPLE_IMAGE_DIR = os.path.abspath(
    os.path.join(
        __file__,
        "..",
        "..",
        "..",
        "docu",
        "file_初赛图像识别示例图片_20260610114326",
        "示例图片",
    )
)


@pytest.fixture(scope="session")
def sample_image_server():
    """启动静态图片服务器，返回可用的端口号。"""

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

    for port in range(18080, 18180):
        try:
            server = HTTPServer(("127.0.0.1", port), QuietHandler)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("无法找到可用端口启动静态图片服务器")

    original_cwd = os.getcwd()
    os.chdir(SAMPLE_IMAGE_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # 等待服务器就绪
    for _ in range(50):
        try:
            import socket

            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except Exception:
            time.sleep(0.05)

    yield port

    server.shutdown()
    os.chdir(original_cwd)


@pytest.fixture
def client():
    return TestClient(app)


def _image_url(port: int, filename: str) -> str:
    return f"http://127.0.0.1:{port}/{urllib.parse.quote(filename)}"


def _make_payload(request_id: str, task_type: str, image_url: str, meta: dict):
    return {
        "request_id": request_id,
        "session_id": "test-session",
        "task_type": task_type,
        "image": {"format": "url", "data": image_url},
        "meta": meta,
    }


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    for task in ("classify", "detect", "ocr"):
        assert task in data["supported_tasks"]


def test_unsupported_task_returns_ok_false(client, sample_image_server):
    url = _image_url(sample_image_server, "classify l1.png")
    payload = _make_payload("req-unsupported", "foo", url, {})
    resp = client.post("/infer", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "不支持" in data["message"]
