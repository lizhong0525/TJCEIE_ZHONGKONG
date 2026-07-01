import time
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import classify
import detect
import ocr
from image_io import load_image_from_url


APP_NAME = "contestant-algo-gateway-service"
APP_VERSION = "0.3.0"

# 与初赛平台对齐：当前仅三类视觉 task_type
_SUPPORTED_TASKS = ["classify", "detect", "ocr"]


class ImagePayload(BaseModel):
    format: str = Field(default="url")
    data: str


class InferRequest(BaseModel):
    request_id: str
    session_id: str
    task_type: str
    image: ImagePayload
    meta: Dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _failure_envelope(
    payload: InferRequest, task_type: str, message: str, elapsed_ms: int
) -> Dict[str, Any]:
    return {
        "request_id": payload.request_id,
        "task_type": task_type,
        "ok": False,
        "result": None,
        "elapsed_ms": elapsed_ms,
        "message": message,
    }


def _success_envelope(
    payload: InferRequest, task_type: str, result: Dict[str, Any], elapsed_ms: int
) -> Dict[str, Any]:
    return {
        "request_id": payload.request_id,
        "task_type": task_type,
        "ok": True,
        "result": result,
        "elapsed_ms": elapsed_ms,
        "message": "",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "supported_tasks": list(_SUPPORTED_TASKS),
        "service": APP_NAME,
        "version": APP_VERSION,
        "bridge_mode": "local",
    }


@app.post("/infer")
def infer(payload: InferRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    task_type = payload.task_type.strip().lower()

    try:
        image = load_image_from_url(payload.image.data)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return _failure_envelope(
            payload, task_type, f"图片加载失败: {exc}", elapsed_ms
        )

    try:
        if task_type == "classify":
            result = classify.do_classify(image, payload.meta)
        elif task_type == "detect":
            result = detect.do_detect(image, payload.meta)
        elif task_type == "ocr":
            result = ocr.do_ocr(image, payload.meta)
        else:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return _failure_envelope(
                payload,
                task_type,
                f"不支持的 task_type: {task_type}，当前仅支持 {_SUPPORTED_TASKS}",
                elapsed_ms,
            )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return _failure_envelope(
            payload, task_type, f"推理异常: {exc}", elapsed_ms
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return _success_envelope(payload, task_type, result, elapsed_ms)
