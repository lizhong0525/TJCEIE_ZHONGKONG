# 选手算法服务-test（Python / FastAPI）

本目录是「选手本地算法服务」的**参考实现**，与初赛评测使用的 HTTP 契约一致，用于与 Agent 网关或浏览器联调。实现见根目录 **`app.py`**（`APP_VERSION` 当前为 **0.2.0**）。

- `GET /health`：在线状态与 `supported_tasks`
- `POST /infer`：统一评测请求，返回占位 `result`（非真实推理）

更完整的字段说明见仓库根目录 **`选手端 算法Agent网关 和返回数据结构说明.md`**（与本服务不一致时以 **`app.py`** 为准）。

---

## 1. 启动方式

### Windows（推荐）

双击同目录 **`一键启动-选手算法服务.bat`**：会自动创建 `.venv`、安装依赖并启动。

### 手动（PowerShell）

在**本目录**（与 `app.py` 同级）执行：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

默认监听 **`http://127.0.0.1:8000`**。可打开 **`http://127.0.0.1:8000/docs`** 查看 OpenAPI。

依赖见 **`requirements.txt`**（`fastapi`、`uvicorn[standard]`）。

---

## 2. 参赛端配置

在参赛端「评测连接 / Agent 网关」中填写 **Base URL**（无末尾路径），例如：

- `http://127.0.0.1:8000`

平台会请求：

- `GET {base}/health`
- `POST {base}/infer`

本服务已启用 **`CORSMiddleware`**（`allow_origins=["*"]`），便于浏览器跨域联调。

---

## 3. `GET /health` 响应示例

与 `health()` 返回一致（`supported_tasks` 顺序与代码中 `_SUPPORTED_TASKS` 相同）：

```json
{
  "status": "ok",
  "supported_tasks": ["classify", "ocr", "detect"],
  "service": "contestant-algo-test-service",
  "version": "0.2.0",
  "bridge_mode": "mock-local"
}
```

---

## 4. `POST /infer` 请求体

| 字段 | 说明 |
|------|------|
| `request_id` | 必填，字符串；响应中原样回显 |
| `session_id` | 必填，字符串；**本示例服务响应中不回传** |
| `task_type` | 必填；会先 `strip().lower()`，仅支持 `classify` / `ocr` / `detect` |
| `image` | 必填；`format` 默认 `"url"`，`data` 为题图 URL 或任意种子字符串 |
| `meta` | 可选；省略时等价 `{}`（Pydantic 默认） |

请求示例：

```json
{
  "request_id": "eval-1001-1",
  "session_id": "team-1",
  "task_type": "detect",
  "image": {
    "format": "url",
    "data": "https://example.com/demo-image.jpg"
  },
  "meta": {
    "difficulty": "L1",
    "coord_mode": "pixel",
    "class_names": ["defect", "valve"],
    "extra": {}
  }
}
```

---

## 5. `POST /infer` 成功响应信封

字段顺序与 `app.py` 中返回字典一致：

```json
{
  "request_id": "eval-1001-1",
  "task_type": "detect",
  "ok": true,
  "result": { },
  "elapsed_ms": 122,
  "message": ""
}
```

- `ok === false` 时：`result` 为 `null`，`message` 为非空说明。
- `elapsed_ms` 为整数毫秒（含前置睡眠，见下文）。

---

## 6. 各 `task_type` 的 `result` 形状（本服务实际返回）

### `detect`

本服务只返回 **`result.targets`**（像素中心点），**不**返回 `boxes` / 归一化 `xyxy`：

```json
{
  "request_id": "eval-1001-1",
  "task_type": "detect",
  "ok": true,
  "result": {
    "targets": [
      {
        "label": "defect",
        "cx": 320.0,
        "cy": 240.0,
        "score": 0.942
      }
    ]
  },
  "elapsed_ms": 122,
  "message": ""
}
```

- `label`：若 `meta.class_names` 非空则从其中随机选一，否则为 `"defect"`。
- `cx` / `cy`：在约 `80～560`、`60～420` 像素范围内由 `image.data` 派生的稳定随机数生成；`score` 在约 `0.9～0.99`。
- 平台判分要求 `coord_mode` 为 **`pixel`** 等约定以赛题与主文档为准；本服务仅做形状演示。

### `ocr`

- 若 `meta.expected.text` 或 `meta.samples[0].expected.text`（后者覆盖前者）经 `strip()` 非空，则 `{"text": "<该字符串>"}`。
- 否则 `{"text": "DEMO-<8位大写十六进制>"}`（由 `image.data` 稳定哈希得到）。

### `classify`

- 候选标签来自 `meta.class_names`；若存在 `meta.samples[0].meta.class_names` 列表则**替换**顶层候选。
- 候选非空时从中稳定随机选一项：`{"label": "..."}`。
- 候选为空时从 **`["normal", "alarm", "offline"]`** 中稳定随机选一。

---

## 7. 环境变量与 `meta.extra`

| 项 | 说明 |
|----|------|
| `MOCK_DELAY_MS` | 默认推理前睡眠毫秒数，缺省 **120**（可被 `meta.extra.delay_ms` 覆盖） |
| `meta.extra.delay_ms` | 整数，本次睡眠毫秒数；`<=0` 则不睡眠 |
| `meta.extra.force_error` | 为真时本次直接返回 `ok: false`（仍含 `elapsed_ms`） |

若 `meta.extra` 存在但不是对象，则按未配置处理：使用 `MOCK_DELAY_MS`/120，且不强制错误。

---

## 8. 联调定位

- 生产链路一般为：平台调度 → Agent 网关 → 本队算法进程；本仓库可直接作为「算法进程」本地替身。
- 也可由 Agent 将 `/infer` **原样转发**到本服务，用于验证 JSON 契约与超时行为。
