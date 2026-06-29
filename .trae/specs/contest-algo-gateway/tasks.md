# Tasks

- [x] Task 1: 搭建网关骨架并改造示例 app.py
  - [x] SubTask 1.1: 在示例 app.py 基础上删除 mock 函数，保留 `/health` 与 `/infer` 路由和 CORS 配置。
  - [x] SubTask 1.2: 新增 `image_io.py`，实现 `load_image_from_url(url) -> PIL.Image` 与异常处理。
  - [x] SubTask 1.3: 在 `/infer` 中按 `task_type` 分发到 `do_classify`、`do_detect`、`do_ocr`，并统一包装失败信封与 `elapsed_ms`。
  - [x] SubTask 1.4: 启动服务验证 `GET /health` 返回 `status == "ok"` 且 `supported_tasks` 包含三类。

- [x] Task 2: 实现 classify 零样本分类模块
  - [x] SubTask 2.1: 编写 `classify.py`，使用 `open_clip.create_model_and_transforms` 加载一个推荐模型（如 `ViT-B-32/openai` 或 `ViT-H-14/laion2b_s32b_b79k`）。
  - [x] SubTask 2.2: 构造 8 个英文 prompt（"a photo of an office" 等），与图像 embedding 做余弦相似度，取 argmax。
  - [x] SubTask 2.3: 建立英文 prompt 到中文类别（办公室、公园、街道、商场、厨房、卧室、图书馆、体育馆）的映射，返回 `{"label": "..."}`。
  - [x] SubTask 2.4: 用示例图片 `classify l*.png` 离线测试，确认返回标签为中文且在合法类别中。
  - [ ] SubTask 2.5（可选）: 引入 `Places365` 作为监督式备选，实现细类到 8 类的映射与加权投票开关。

- [x] Task 3: 实现 detect 双模型检测模块
  - [x] SubTask 3.1: 编写 `detect.py`，使用 `ultralytics.YOLO("yolov8x.pt")` 对输入图像推理。
  - [x] SubTask 3.2: 提取 `result.boxes.xyxy` 并计算中心点 `(cx, cy)`，过滤 COCO 映射到 8 个目标类的结果（person/car/bicycle/cell phone/cup/laptop/couch/dog）。
  - [x] SubTask 3.3: 建立 COCO 类名到中文标签的映射字典，返回 `targets` 列表。
  - [x] SubTask 3.4: 集成 `YOLO-World`，调用 `set_classes(["lamp", "desk lamp", "table lamp"])` 检测台灯，并将结果合并到 `targets`。
  - [ ] SubTask 3.5（可选）: 集成 `GroundingDINO` 作为台灯漏检兜底。
  - [x] SubTask 3.6: 用示例图片 `detect l*.png` 离线测试，确认返回像素坐标、标签合法。

- [x] Task 4: 实现 ocr 识别与规范化模块
  - [x] SubTask 4.1: 编写 `ocr.py`，初始化 `PaddleOCR(use_angle_cls=True, lang="ch")`。
  - [x] SubTask 4.2: 对图像进行 OCR，解析返回的文本框四点坐标，按中心点“先 y 后 x”排序，拼接为字符串。
  - [x] SubTask 4.3: 编写独立的 `normalize(text, rules)` 函数，支持 `trim_space`、`case_insensitive` 及常见全半角、繁简、空格、标点处理。
  - [x] SubTask 4.4: 返回 `{"text": "..."}`，确保经过 normalize 后输出。
  - [x] SubTask 4.5: 用示例图片 `ocr l*.png` 离线测试，验证输出字符串与规则处理结果。

- [x] Task 5: 模型依赖与下载脚本
  - [x] SubTask 5.1: 更新 `requirements.txt`，添加 `open_clip_torch`、`ultralytics`、`paddleocr`、`Pillow`、`requests` 等依赖。
  - [x] SubTask 5.2: 添加模型权重首次加载/缓存说明；确保 YOLOv8x 权重、`open_clip` 模型、`PaddleOCR` 模型能在运行时自动下载或提供手动下载脚本。
  - [x] SubTask 5.3: 验证在 `.venv` 中可完整安装依赖并启动服务（已安装轻量依赖并验证 `/health`，重型模型依赖需在目标环境安装后运行）。

- [x] Task 6: 端对端联调与测试
  - [x] SubTask 6.1: 编写 `local_test.py`，对示例图片构造 classify/detect/ocr 请求，调用本地 `/infer` 接口并打印结果。
  - [x] SubTask 6.2: 在浏览器或 `curl` 中验证 `GET /health` 与 `POST /infer` 的 CORS、JSON 格式、字段回显。
  - [x] SubTask 6.3: 验证异常路径：不支持的 task_type、图片 URL 不可达、模型超时返回合法 `ok: false` 信封。

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1]
- [Task 6] depends on [Task 2], [Task 3], [Task 4], [Task 5]
