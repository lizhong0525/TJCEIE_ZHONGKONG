# 算法 Agent 网关服务（三模型整合）Spec

## Why
为参加在线视觉评测，需要在本机部署一个统一的 FastAPI 网关服务，接收平台的 `/health` 与 `/infer` 请求，并分别调用图像分类、目标检测、文字识别三个模型流水线。三个题型均为 GitHub 上已有预训练权重的模型，采用零样本或预训练方案，避免自行训练。

## What Changes
- 以 `docu/file_选手算法Agent网关服务-python示例_20260531133855/选手算法Agent网关服务-python示例/app.py` 为基础，改造为真实推理服务。
- 新增 `classify.py`：基于 `open_clip` 的零样本场景分类，可选 `Places365` 监督模型作为混淆兜底。
- 新增 `detect.py`：基于 `ultralytics` YOLOv8/v11 检测 8 个 COCO 类，并用 `YOLO-World` 补齐“台灯”，可选 `GroundingDINO` 兜底。
- 新增 `ocr.py`：基于 `PaddleOCR` 进行中英文检测+识别，并接入统一的 `normalize(text, rules)` 后处理。
- 新增 `image_io.py`：统一从 URL 下载图像并转换为模型所需的 `PIL.Image` / numpy。
- 新增 `requirements.txt`：包含 `fastapi`、`uvicorn`、`open_clip_torch`、`ultralytics`、`paddleocr`（及可选 `yolo-world`、`groundingdino-py` 等）。
- 新增本地测试脚本：对示例图片调用三类接口并打印结果。

## Impact
- Affected specs：
  - 网关接口设计：保持 `/health` 与 `/infer` 契约不变。
  - 在线评测算法资料：三类题型的输出格式严格对齐。
- Affected code：
  - 主服务：`app.py`
  - 模型模块：`classify.py`、`detect.py`、`ocr.py`、`image_io.py`
  - 依赖：`requirements.txt`
  - 测试：`tests/test_*.py` 或 `local_test.py`

## ADDED Requirements

### Requirement: 网关基础能力
系统 SHALL 提供一个 FastAPI 服务，暴露 `GET /health` 与 `POST /infer`。

#### Scenario: 健康检查
- **WHEN** 平台请求 `GET /health`
- **THEN** 返回 `{"status": "ok", "supported_tasks": ["classify", "detect", "ocr"], ...}`

#### Scenario: 通用推理信封
- **WHEN** 平台 POST `/infer` 并携带 `request_id`、`task_type`、`image`、`meta`
- **THEN** 响应必须包含 `request_id`（原样回显）、`task_type`、`ok`、`result`、`elapsed_ms`、`message`；成功时 `message` 为空字符串。

### Requirement: 图像加载
系统 SHALL 支持 `image.format == "url"`，从 URL 下载图片并缓存到内存，返回 `PIL.Image`。

#### Scenario: 正常下载
- **WHEN** `image.data` 为可访问的 HTTP/HTTPS 图片 URL
- **THEN** 成功读取 RGB 图像并供后续模型使用。

#### Scenario: 下载失败
- **WHEN** URL 不可达或返回非图片内容
- **THEN** 返回 `ok: false`，`message` 说明图片加载失败，`result` 为 `null`。

### Requirement: classify 图像分类
系统 SHALL 对 8 个固定场景类别（办公室、公园、街道、商场、厨房、卧室、图书馆、体育馆）进行分类，并返回中文标签。

#### Scenario: 主路径（open_clip 零样本）
- **WHEN** 收到 `task_type == "classify"`
- **THEN** 使用 `open_clip` 对图像和 8 个英文 prompt 分别编码，按余弦相似度取 `argmax`，再映射为中文标签返回。

#### Scenario: 混淆兜底（Places365）
- **WHEN** 配置启用 fallback 且 open_clip 在商场/街道或办公室/图书馆等易混类上置信度接近
- **THEN** 同步或异步过一遍 `Places365` 预训练模型，将细类映射到 8 个竞赛类，并以加权投票决定最终标签。

#### Scenario: 标签合法性
- **WHEN** 返回 `result.label`
- **THEN** 必须落在 `meta.class_names` 中（平台下发为中文）。

### Requirement: detect 目标检测
系统 SHALL 检测 9 个固定类别（人、汽车、自行车、手机、水杯、笔记本电脑、台灯、沙发、狗），返回像素中心点坐标。

#### Scenario: 8 个 COCO 类检测
- **WHEN** 收到 `task_type == "detect"`
- **THEN** 使用 `ultralytics` 的 `YOLOv8x`/`yolov8x.pt` 进行检测，将 COCO 英文类别映射为中文标签（person→人, car→汽车, bicycle→自行车, cell phone→手机, cup→水杯, laptop→笔记本电脑, couch→沙发, dog→狗），并取 `((x1+x2)/2, (y1+y2)/2)` 作为像素中心点。

#### Scenario: 台灯类补齐
- **WHEN** YOLO 主线未检测出台灯
- **THEN** 使用 `YOLO-World` 以 `set_classes(["lamp", "desk lamp", "table lamp"])` 进行开放词汇检测，命中结果加入 `targets`。

#### Scenario: 高精度兜底
- **WHEN** 配置启用 GroundingDINO 兜底且台灯仍未检出
- **THEN** 用 `GroundingDINO` 以“台灯 / desk lamp / table lamp”为文本提示再次检测，结果合并。

#### Scenario: 坐标合法性
- **WHEN** 返回 `result.targets`
- **THEN** `cx`、`cy` 为题图左上角为原点的像素坐标，不使用 0~1 归一化。

### Requirement: ocr 文字识别与规范化
系统 SHALL 识别图像中的中英文文本，按位置排序后拼接，再按规则规范化并返回。

#### Scenario: 识别与排序
- **WHEN** 收到 `task_type == "ocr"`
- **THEN** 使用 `PaddleOCR(use_angle_cls=True, lang="ch")` 检测并识别文本框，按文本框中心“先 y 后 x”排序，拼接为完整字符串。

#### Scenario: 规范化后处理
- **WHEN** 得到原始识别字符串
- **THEN** 调用独立的 `normalize(text, rules)` 函数，根据 `meta.normalize_rules`（如 `trim_space`、`case_insensitive`）处理后再返回。

#### Scenario: 常见规则覆盖
- **WHEN** rules 包含全/半角、大小写、首尾空格、标点、繁简等字段
- **THEN** `normalize` 函数集中处理这些规则，避免在识别模块散落。

### Requirement: 超时与异常
系统 SHALL 在单次推理中遵守 `meta.infer_T_max_ms` 时间限制，并返回合法的失败信封。

#### Scenario: 推理超时
- **WHEN** 某模型在限定时间内未完成
- **THEN** 中断并返回 `ok: false`、`result: null`、`message` 包含“推理超时”。

#### Scenario: 不支持的 task_type
- **WHEN** `task_type` 不是 classify/detect/ocr
- **THEN** 返回 `ok: false`，`message` 说明不支持。

## MODIFIED Requirements
无现有代码需要修改；本次基于示例 `app.py` 改造为新服务。

## REMOVED Requirements
无。
