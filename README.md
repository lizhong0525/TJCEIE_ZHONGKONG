# TJCEIE_ZHONGKONG - 中控杯在线视觉评测算法网关

面向中控杯初赛在线评测的算法 Agent 网关服务，基于 FastAPI 构建统一推理接口，集成图像分类、目标检测和文字识别三种视觉任务。

## 项目结构

```
├── service/                          # 核心推理服务
│   ├── app.py                         # FastAPI 主入口，路由分发 /health 和 /infer
│   ├── classify.py                    # 图像分类（OpenCLIP 零样本，8 类场景）
│   ├── detect.py                      # 目标检测（YOLOv8x + YOLO-World 补齐台灯）
│   ├── ocr.py                         # 文字识别（PaddleOCR + 规范化后处理）
│   ├── image_io.py                    # 统一图像加载（URL → PIL.Image）
│   ├── download_models.py             # 预下载模型权重脚本
│   ├── local_test.py                  # 本地测试脚本（对示例图片调用三类接口）
│   ├── requirements.txt               # Python 依赖
│   └── tests/test_basics.py           # 基础单元测试
├── docu/                              # 赛事资料与示例
│   ├── 01_网关接口设计.md              # 平台接口契约文档
│   ├── 02_在线评测算法资料.md          # 评测题型、判分逻辑与计分说明
│   ├── 初赛图像识别示例图片/            # classify / detect / ocr 各难度示例图
│   └── 选手算法Agent网关服务-python示例/ # 官方 Mock 服务参考实现
└── .gitignore
```

## 三大题型

| 题型 | task_type | 说明 | 核心模型 |
|------|-----------|------|----------|
| 图像分类 | `classify` | 8 类场景（办公室、公园、街道、商场、厨房、卧室、图书馆、体育馆） | OpenCLIP 零样本 |
| 目标检测 | `detect` | 9 类目标（人、汽车、自行车、手机、水杯、笔记本电脑、台灯、沙发、狗），返回像素中心点 | YOLOv8x + YOLO-World |
| 文字识别 | `ocr` | 中英文检测+识别，按位置排序拼接，支持规范化规则 | PaddleOCR |

## 快速开始

### 1. 环境准备

```bash
# 建议使用 Python 3.10+
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
```

### 2. 安装依赖

```bash
cd service
pip install -r requirements.txt
```

### 3. 启动服务

```bash
cd service
uvicorn app:app --host 0.0.0.0 --port 8000
```

服务启动后：
- 健康检查：`GET http://127.0.0.1:8000/health`
- 推理接口：`POST http://127.0.0.1:8000/infer`
- API 文档：`http://127.0.0.1:8000/docs`

### 4. 本地测试

```bash
cd service
python local_test.py
```

## 接口说明

### GET /health

```json
{
  "status": "ok",
  "supported_tasks": ["classify", "detect", "ocr"],
  "service": "contestant-algo-gateway-service",
  "version": "0.3.0",
  "bridge_mode": "local"
}
```

### POST /infer

请求体：

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_id` | string | 平台生成的唯一请求 ID，响应原样回显 |
| `session_id` | string | 会话 ID |
| `task_type` | string | `classify` / `detect` / `ocr` |
| `image` | object | `{"format": "url", "data": "https://..."}` |
| `meta` | object | 评测上下文（难度、类别列表、超时限制等） |

响应体：

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_id` | string | 与请求一致 |
| `task_type` | string | 与请求一致 |
| `ok` | boolean | 是否推理成功 |
| `result` | object/null | 成功时包含结果，失败时为 null |
| `elapsed_ms` | number | 推理耗时（毫秒） |
| `message` | string | 失败原因，成功时为空字符串 |

## 技术栈

- **Web 框架**：FastAPI + Uvicorn
- **图像分类**：OpenCLIP（零样本分类）
- **目标检测**：Ultralytics YOLOv8x + YOLO-World（开放词汇检测）
- **文字识别**：PaddleOCR（中英文检测与识别）
- **图像处理**：Pillow、NumPy
- **深度学习**：PyTorch

## 评测计分

初赛在线评测共 60 分，由 3 类 x 3 档 = 9 个槽位组成：

| 题型 | L1 | L2 | L3 | 小计 |
|------|-----|-----|-----|------|
| classify | 4.8 | 6.0 | 7.2 | 18 分 |
| detect | 6.0 | 7.8 | 10.2 | 24 分 |
| ocr | 4.8 | 6.0 | 7.2 | 18 分 |

## 注意事项

- 检测任务坐标必须为**像素坐标**（左上角原点），禁止使用归一化坐标
- 分类任务返回的标签必须与平台下发的 `meta.class_names` 中的中文标签一致
- OCR 任务需按 `meta.normalize_rules` 对输出做规范化处理
- 单次推理须在 `meta.infer_T_max_ms` 内完成
