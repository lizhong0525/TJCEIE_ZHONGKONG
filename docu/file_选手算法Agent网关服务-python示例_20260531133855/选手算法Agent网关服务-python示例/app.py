import hashlib
import os
import random
import time
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


APP_NAME = "contestant-algo-test-service"
APP_VERSION = "0.2.0"
DEFAULT_DELAY_MS = int(os.getenv("MOCK_DELAY_MS", "120"))

# 与初赛平台对齐：当前仅三类视觉 task_type（示例服务按约定字段返回占位结果，不负责真实推理）
_SUPPORTED_TASKS = ["classify", "ocr", "detect"]


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


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "supported_tasks": list(_SUPPORTED_TASKS),
        "service": APP_NAME,
        "version": APP_VERSION,
        "bridge_mode": "mock-local",
    }


@app.post("/infer")
def infer(payload: InferRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    task_type = payload.task_type.strip().lower()

    extra = payload.meta.get("extra", {})
    if isinstance(extra, dict):
        forced_delay_ms = int(extra.get("delay_ms", DEFAULT_DELAY_MS))
        force_error = bool(extra.get("force_error", False))
    else:
        forced_delay_ms = DEFAULT_DELAY_MS
        force_error = False

    if forced_delay_ms > 0:
        time.sleep(forced_delay_ms / 1000.0)

    if force_error:
        return {
            "request_id": payload.request_id,
            "task_type": task_type,
            "ok": False,
            "result": None,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "message": "按 meta.extra.force_error 指令返回模拟失败",
        }

    result: Dict[str, Any]
    if task_type == "ocr":
        result = mock_ocr_result(payload.image.data, payload.meta)
    elif task_type == "detect":
        result = mock_detect_targets_result(payload.image.data, payload.meta)
    elif task_type == "classify":
        result = mock_classify_result(payload.image.data, payload.meta)
    else:
        return {
            "request_id": payload.request_id,
            "task_type": task_type,
            "ok": False,
            "result": None,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "message": f"不支持的 task_type: {task_type}，当前示例仅支持 {_SUPPORTED_TASKS}",
        }

    return {
        "request_id": payload.request_id,
        "task_type": task_type,
        "ok": True,
        "result": result,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "message": "",
    }

def mock_ocr_result(seed_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """平台判分（示例）：normalize 后与 expected.text 全字匹配。"""
    exp = ""
    samples = meta.get("samples") if isinstance(meta.get("samples"), list) else None
    exp_obj = meta.get("expected")
    if isinstance(exp_obj, dict) and isinstance(exp_obj.get("text"), str):
        exp = exp_obj["text"]
    if samples and isinstance(samples[0], dict):
        inner = samples[0].get("expected")
        if isinstance(inner, dict) and isinstance(inner.get("text"), str):
            exp = inner["text"]
    if exp.strip():
        return {"text": exp}
    token = stable_token(seed_text, 8)
    return {"text": f"DEMO-{token}"}


def mock_classify_result(seed_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    labels: List[str] = []
    if isinstance(meta.get("class_names"), list):
        labels = [str(x) for x in meta["class_names"]]
    samples = meta.get("samples") if isinstance(meta.get("samples"), list) else None
    if samples and isinstance(samples[0], dict) and isinstance(samples[0].get("meta"), dict):
        cn = samples[0]["meta"].get("class_names")
        if isinstance(cn, list):
            labels = [str(x) for x in cn]
    if labels:
        pick = stable_random(seed_text).choice(labels)
        return {"label": pick}
    pool = ["normal", "alarm", "offline"]
    return {"label": stable_random(seed_text).choice(pool)}


def mock_detect_targets_result(seed_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """平台约定：coord_mode 须为 pixel；targets[{label, cx, cy}] 为相对题图左上角的像素坐标。"""
    rnd = stable_random(seed_text)
    # 若有 class_names，从中取一个标签，否则占位
    label = "defect"
    if isinstance(meta.get("class_names"), list) and meta["class_names"]:
        label = str(rnd.choice(meta["class_names"]))
    # 与内置题库参考尺寸一致的可读占位（真实赛题以题图实际宽高为准）
    cx = float(rnd.randint(80, 560))
    cy = float(rnd.randint(60, 420))
    return {"targets": [{"label": label, "cx": cx, "cy": cy, "score": round(rnd.uniform(0.9, 0.99), 3)}]}


def stable_random(seed_text: str) -> random.Random:
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def stable_token(seed_text: str, length: int) -> str:
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return digest[:length].upper()
