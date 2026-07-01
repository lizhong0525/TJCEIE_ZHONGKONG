"""本地端到端测试脚本：不依赖外部图片 URL，使用 TestClient 调用服务。"""

import os
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient

from app import app


SAMPLE_IMAGE_DIR = os.path.abspath(
    os.path.join(
        __file__,
        "..",
        "..",
        "docu",
        "file_初赛图像识别示例图片_20260610114326",
        "示例图片",
    )
)

_STATIC_PORT = None
_STATIC_SERVER_THREAD = None


def _start_static_server():
    """在后台线程启动一个静态 HTTP 服务器，用于提供示例图片。"""
    global _STATIC_PORT, _STATIC_SERVER_THREAD

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

    os.chdir(SAMPLE_IMAGE_DIR)
    _STATIC_PORT = port
    _STATIC_SERVER_THREAD = threading.Thread(target=server.serve_forever, daemon=True)
    _STATIC_SERVER_THREAD.start()

    # 等待服务器就绪
    for _ in range(50):
        try:
            import socket

            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except Exception:
            time.sleep(0.05)

    return port


def _image_url(filename: str) -> str:
    return f"http://127.0.0.1:{_STATIC_PORT}/{urllib.parse.quote(filename)}"


def _make_infer_payload(request_id: str, task_type: str, image_url: str, meta: dict):
    return {
        "request_id": request_id,
        "session_id": "local-test-session",
        "task_type": task_type,
        "image": {"format": "url", "data": image_url},
        "meta": meta,
    }


def main():
    port = _start_static_server()
    print(f"静态图片服务器已启动: http://127.0.0.1:{port}/")
    print(f"示例图片目录: {SAMPLE_IMAGE_DIR}")
    print()

    client = TestClient(app)

    # 1) /health
    print("=== GET /health ===")
    health_resp = client.get("/health")
    print(health_resp.status_code, health_resp.json())
    health = health_resp.json()
    assert health.get("status") == "ok", "健康检查状态应为 ok"
    supported = health.get("supported_tasks", [])
    for task in ("classify", "detect", "ocr"):
        assert task in supported, f"supported_tasks 应包含 {task}"
    print("健康检查通过\n")

    # 2) 对每张示例图片进行 /infer
    classify_meta = {
        "class_names": ["办公室", "公园", "街道", "商场", "厨房", "卧室", "图书馆", "体育馆"]
    }
    detect_meta = {
        "class_names": ["人", "汽车", "自行车", "手机", "水杯", "笔记本电脑", "台灯", "沙发", "狗"],
        "coord_mode": "pixel",
        "scoring": "center_in_box",
    }
    ocr_meta = {"normalize_rules": {"trim_space": True, "case_insensitive": False}}

    task_configs = {
        "classify": classify_meta,
        "detect": detect_meta,
        "ocr": ocr_meta,
    }

    sample_images = [
        ("classify l1.png", "classify"),
        ("classify l2.png", "classify"),
        ("classify l3.png", "classify"),
        ("detect l1.png", "detect"),
        ("detect l2.png", "detect"),
        ("detect l3.png", "detect"),
        ("ocr l1.png", "ocr"),
        ("ocr l2.png", "ocr"),
        ("ocr l3.png", "ocr"),
    ]

    for filename, task in sample_images:
        url = _image_url(filename)
        meta = task_configs[task]
        payload = _make_infer_payload(f"req-{task}-{filename}", task, url, meta)
        print(f"=== POST /infer | {task} | {filename} ===")
        print(f"URL: {url}")
        try:
            resp = client.post("/infer", json=payload)
            data = resp.json()
            print(f"status={resp.status_code}, ok={data.get('ok')}, elapsed_ms={data.get('elapsed_ms')}")
            print(f"result={data.get('result')}")
            print(f"message={data.get('message')!r}")
        except Exception as exc:
            print(f"调用异常: {exc}")
        print()

    # 3) 不支持的 task_type
    print("=== 不支持 task_type 测试 ===")
    bad_payload = _make_infer_payload(
        "req-unsupported", "foo", _image_url("classify l1.png"), classify_meta
    )
    resp = client.post("/infer", json=bad_payload)
    data = resp.json()
    print(f"status={resp.status_code}, ok={data.get('ok')}, message={data.get('message')!r}")
    assert data.get("ok") is False, "不支持的 task_type 应返回 ok=false"
    print("不支持 task_type 测试通过\n")

    # 4) 不可达图片 URL
    print("=== 不可达图片 URL 测试 ===")
    unreachable_payload = _make_infer_payload(
        "req-unreachable", "classify", "http://127.0.0.1:19999/not_exist.png", classify_meta
    )
    resp = client.post("/infer", json=unreachable_payload)
    data = resp.json()
    print(f"status={resp.status_code}, ok={data.get('ok')}, message={data.get('message')!r}")
    assert data.get("ok") is False, "不可达图片 URL 应返回 ok=false"
    print("不可达图片 URL 测试通过\n")

    print("本地端到端测试完成。")


if __name__ == "__main__":
    main()
