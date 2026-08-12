# Tasks

- [x] Task 1: 搭建工程骨架与配置加载
  - [x] SubTask 1.1: 创建 `algorithm_service/` 目录、`pyproject.toml` 声明 Python 3.11、依赖 `aiohttp, pyyaml, opencv-python, numpy, requests, websockets, pyorbbecsdk`（pyorbbecsdk 以可选依赖标注，未安装时 health 仍 200，但赛题返回 camera not ready）
  - [x] SubTask 1.2: 实现 `config/site.yaml` 加载与 `SiteConfig` dataclass，含占位校验
  - [x] SubTask 1.3: 实现 `tools/calibrate.py`：交互式填表后写回 `config/site.yaml`

- [x] Task 2: 实现 HTTP 服务框架
  - [x] SubTask 2.1: `aiohttp` 应用 + 4 个接口路由 + 统一 JSON 响应包装
  - [x] SubTask 2.2: `asyncio.Lock` 串行化赛题调用，busy 时立即返回
  - [x] SubTask 2.3: 启动入口 `python -m algorithm_service`，默认 `0.0.0.0:5000`，命令行支持 `--host/--port/--config`

- [x] Task 3: 硬件/视觉封装
  - [x] SubTask 3.1: `hardware/arm.py`（B9Client 同步封装 + safe_home / line_to / enable / disable / status）
  - [x] SubTask 3.2: `hardware/hand.py`（O10Client 同步封装 + set_pos / errors 后台监控）
  - [x] SubTask 3.3: `vision/camera.py`（pyorbbecsdk 采集 + 内参/畸变 + pixel_to_base）
  - [x] SubTask 3.4: `planner/actions.py`（safe_home / approach / pick / place + 安全区校验）

- [x] Task 4: 赛题 1（控制面板）
  - [x] SubTask 4.1: 视觉检测：6 按钮亮灯识别（颜色阈值 + 圆形拟合），参数在 `config/vision/task1.yaml`
  - [x] SubTask 4.2: 按钮坐标 + 拨杆状态机，按钮类型 tap / 拨杆 toggle
  - [x] SubTask 4.3: `tasks/task1.py` 串接 拍照→识别→操作→复位

- [x] Task 5: 赛题 2（数字长方体）
  - [x] SubTask 5.1: 视觉检测：长方体检测 + 数字 OCR（用 OpenCV + tesseract 已安装的中文/英文库）
  - [x] SubTask 5.2: 排序与槽位分配，参数 `digit_blocks.placement_order_target`
  - [x] SubTask 5.3: `tasks/task2.py` 串接 拍照→识别→排序→逐个 pick&place

- [x] Task 6: 赛题 3（形状入槽）
  - [x] SubTask 6.1: 视觉检测：多面体形状分类（圆形/方形/异形；几何特征：圆度、轮廓多边形逼近）
  - [x] SubTask 6.2: 形状-槽位映射（按 `shapes[].name` 匹配）
  - [x] SubTask 6.3: `tasks/task3.py` 串接 拍照→分类→逐个 pick&place

- [x] Task 7: 自检与文档
  - [x] SubTask 7.1: `tools/selftest.py` 启动本地 mock + 调用 4 个接口并打印报告
  - [x] SubTask 7.2: `README.md`（用户未明确要求文档；如有可放运行/标定说明）— 仅在用户后续要求时创建，本期不创建

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4/5/6 各自依赖 Task 2、Task 3
- Task 7 依赖 Task 4/5/6

# Parallelizable
- Task 1.1、3.1、3.2 可并行
- Task 4/5/6 三个赛题实现可并行
