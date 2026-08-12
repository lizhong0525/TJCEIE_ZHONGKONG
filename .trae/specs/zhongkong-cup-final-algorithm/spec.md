# 中控杯复赛 · 选手算法服务 Spec

## Why
复赛 WPF 测试工具通过 `GET /api/health` + 三个 `POST /api/task*/execute` 调用选手的 HTTP 算法服务，由算法服务自行驱动 FTArm B9 机械臂、灵巧手、视觉完成赛题 1（控制面板亮灯/拨杆）、赛题 2（数字长方体排序摆放）、赛题 3（形状分类入槽）三道题目。

## What Changes
- 新增 `algorithm_service/` Python 3.11 软件包：HTTP 算法服务、配置加载、硬件/视觉/规划/抓取 4 个子层。
- 新增 `config/site.yaml`：相机内参/畸变、手眼矩阵、操作台尺寸与安全区、控制面板 6 按钮坐标、形状与槽位/数字赛具参数；**长度数值留占位，文档/代码以 `__现场标定后填入__` 标记**。
- 新增 `tools/calibrate.py`：一次性写入上述占位参数，落地为可加载 YAML。
- 新增 `tools/selftest.py`：启动服务并用接口示例 + 测试工具做端到端自检。
- 对接现成外部件：FTArm B9 HTTP/WS 服务（8087）、O10 灵巧手 HTTP/WS 服务（8088）、`pyorbbecsdk`（Gemini335 相机）；这些不属于本仓库代码，但通过配置/接口调用。

## 业务边界
- **单机械臂 + 单灵巧手，居中布置**（用户已确认）。机械臂采用右臂工作区镜像坐标 Y≥0；灵巧手 `hand_type: "right"`。若现场反向，配置文件翻转即可。
- 三个赛题共享同一服务（同一进程同时只能执行一个赛题），互斥由测试工具侧按按钮触发保证。
- 软件只关心 `success` 字段，不解析返回数据；因此算法规格只暴露最小成功返回 `{"success": true, "message": "taskX ok"}`。
- 健康检查与赛题接口独立：健康检查不阻塞硬件，赛题接口可阻塞数秒~数十秒（机械臂运动上限 60s，回放上限 300s）。

## Impact
- Affected specs：无（首次落库）
- Affected code：仓库内所有新增代码与配置位于 `algorithm_service/`、`config/`、`tools/`，不修改 `docs/`、`接口示例/`、`测试工具/`。

---

## ADDED Requirements

### Requirement: 服务框架
系统 SHALL 提供基于 Python 3.11、`aiohttp.web` 的选手算法服务，默认监听 `0.0.0.0:5000`，实现 `GET /api/health`、`POST /api/task1/execute`、`POST /api/task2/execute`、`POST /api/task3/execute`，请求体允许为空 JSON `{}`，统一 `Content-Type: application/json; charset=utf-8`，响应统一形如 `{"success": bool, "message": str}`。

#### Scenario: 健康检查
- **WHEN** 测试工具 `GET /api/health`
- **THEN** 在 200ms 内返回 `{"success": true, "message": "ready"}`；若硬件/相机初始化失败仍返回 `success: false` + 简短 message，绝不抛 5xx。

#### Scenario: 赛题调用
- **WHEN** 测试工具 `POST /api/task*/execute`
- **THEN** 服务记录开始时间 → 串行执行对应赛题任务 → 任务成功返回 `{"success": true, "message": "taskX ok"}`，任意阶段失败返回 `{"success": false, "message": "<错误摘要>"}`。服务不解析额外字段，因此 message 只用于日志与告警。

#### Scenario: 并发互斥
- **WHEN** 同一赛题或不同赛题被并发触发
- **THEN** 服务内以 `asyncio.Lock` 串行化执行；正在执行时新请求立即返回 `{"success": false, "message": "busy"}`。

### Requirement: 配置与标定
系统 SHALL 通过 `config/site.yaml` 加载所有可现场标定的参数；不依赖任何硬编码长度。

#### Scenario: 默认配置加载
- **WHEN** 服务启动且 `config/site.yaml` 存在
- **THEN** 解析为 `SiteConfig` 数据类（dataclass），缺失键时记录 warning 并使用占位（`__现场标定后填入__`），启动但不阻塞。

#### Scenario: 写入现场标定
- **WHEN** 操作员执行 `python -m tools.calibrate` 并按提示填入：
  - 相机内参 `fx, fy, cx, cy`、畸变 `k1, k2, p1, p2`、手眼矩阵 `T_base_camera (4×4)`
  - 操作台台面尺寸 `length, width, height` 与安全区边界 `safe_box`
  - 控制面板 6 按钮坐标（`buttons[0..5]`，字段：颜色、类型 `push|toggle`、目标位姿 `x,y,z`），位置按用户描述的"左：红上下 2 + 中：上黄下拨杆（上下拨）+ 右上下绿 2"分布
  - 数字赛具参数 `digit_blocks.digit_count`（具体数字留占位）、`digit_blocks.placement_order_target`（如"按升序"）
  - 形状赛具 `shapes[].name`（如 圆形/方形/异形）、`shapes[].slots[].x,y,z`（槽位阵列）
- **THEN** 校验后覆盖写入 `config/site.yaml`，并立刻可被服务加载。

#### Scenario: 占位未填
- **WHEN** 任何被规划/标定流程读取的数值仍是占位
- **THEN** 在日志中输出明显告警 `WARN: <field> 未标定，行为将不可靠`；不抛异常中断启动。

### Requirement: 机械臂控制封装
系统 SHALL 封装 `ArmClient`，通过 `B9Client` 调 `http://<host>:8087`，使用右臂工作区参数 `mode=right_arm`、`right={x,y,z,roll,pitch,yaw}`、`right_joints=[7]`，默认推荐姿态 `(-3.141, -1.552, 3.141)`。

#### Scenario: 安全开机
- **WHEN** 赛题任务启动
- **THEN** 依次 `GET /api/status` → `GET /api/motors`（确认 `fault=0, has_feedback=1`）→ `POST /api/enable` → `GET /api/motors`（确认 `enabled=1`）。任一步骤失败立即返回 `success=false` 并附 message。

#### Scenario: 末端直线运动
- **WHEN** 业务调用 `arm.line_to(x, y, z)`
- **THEN** 走 `POST /api/end_effector {cartesian_linear: true}`，目标在工作域 Y∈[__现场标定后填入__], Z∈[__现场标定后填入__]（占位）时断言返回 message 不含 `OMPL`；超出工作域时**自动回退**为自由路径并打 warning，**不**作为失败。

#### Scenario: 慢速+收尾
- **WHEN** 赛题完成
- **THEN** 末端降至安全低 z（占位），速度 `velocity_scaling=0.05`，最后 `POST /api/disable` 软急停（赛前手册已记录"会下坠"——只用于异常收尾，正常比赛流程可不调用）。

### Requirement: 灵巧手控制封装
系统 SHALL 封装 `HandClient`，调 `http://<host>:8088`，右手 `hand_type=right`；统一使用归一化 `POST /api/set_pos`（10 维 [0,1]）。

#### Scenario: 抓取姿态
- **WHEN** 业务调用 `hand.pose(name)`，name ∈ {`open`, `grasp_digit`, `grasp_shape`, `close`}
- **THEN** 调用 `set_pos` 对应 10 维数组（数值在配置 `hand/poses.yaml` 维护；初版提供 4 个默认姿态：open=[1]*10、close=[0]*10、grasp_digit/ grp_shape 由实现期通过示教回放或默认估值填入）。

#### Scenario: 错误监控
- **WHEN** 任务执行中
- **THEN** 异步后台每 200ms `GET /api/errors`，任一 `error_codes[i] != 0` 立即停止当前动作并降级为 `success=false`。

### Requirement: 视觉子系统
系统 SHALL 通过 `pyorbbecsdk`（Orbbec Gemini335 Python 绑定）获取彩色帧 + 深度帧 + 相机内参，提供 `Vision` 模块。

#### Scenario: 单帧采集
- **WHEN** 业务调用 `vision.capture()`
- **THEN** 返回 `{"color": np.ndarray(BGR), "depth": np.ndarray(uint16, mm), "intrinsics": (fx,fy,cx,cy), "distortion": (k1,k2,p1,p2)}`；采集失败抛 `VisionError` 由赛题层转为 `success=false`。

#### Scenario: 手眼变换
- **WHEN** 业务调用 `vision.pixel_to_base(u, v, depth_mm)`
- **THEN** 先去畸变 → 相机坐标 → 用 `T_base_camera` 变换到基座坐标；返回 `{"x": float, "y": float, "z": float}`（m）。

#### Scenario: 启动期检测
- **WHEN** 服务启动或相机断流
- **THEN** 连续 3 次 `capture()` 失败则 `Vision.health_ready = False`；`/api/health` 维持 success，赛题开始时若仍未就绪则直接返回 `{"success": false, "message": "camera not ready"}`。

### Requirement: 规划与动作库
系统 SHALL 提供 `planner` 子包，对外暴露高层动作： `arm.safe_home()`、`arm.look_at(target)`、`arm.approach(target)`、`arm.pick(target, hand_pose)`、`arm.place(slot)`。

#### Scenario: 标准抓取流水线
- **WHEN** 业务调用 `arm.pick(target, hand_pose)`
- **THEN** 顺序：① `hand.pose('open')` → ② `arm.line_to(target.above)`（安全抬升 z+`__现场标定后填入__` m）→ ③ `arm.line_to(target.pick)`（直线下降到抓取点）→ ④ `hand.pose(hand_pose)` → ⑤ `arm.line_to(target.above)` 抬升；任一步失败抛 `PickError`。

#### Scenario: 安全区校验
- **WHEN** 任何末端目标被提交
- **THEN** 校验目标在 `config.site.safe_box` 范围内（占位值），越界拒绝并 `success=false`。

### Requirement: 赛题 1（控制面板操作）
系统 SHALL 在 `POST /api/task1/execute` 触发时执行一次完整的"拍照-识别-操作-复位"。

#### Scenario: 任务流程
- **WHEN** 测试工具调用赛题 1
- **THEN** 服务：
  1. `arm.safe_home()` → `arm.look_at(panel)`（面板中心由配置 `panel.center` 给出）
  2. `vision.capture()` → 检测 6 个按钮中"亮灯"的索引（红上下2 / 上黄下拨杆 / 绿上下2；算法为颜色阈值 + 圆形拟合，参数在 `config/vision/task1.yaml`）
  3. 若识别到拨杆（中间下黄）：`arm.pick + place` 到上/下位（由"前次位置"判断，状态机在内存里维护）
  4. 若识别到按钮：`arm.line_to(button_pos) + hand.pose('tap')` 单击；按钮坐标全部来自 `config.buttons`
  5. 任务结束末端回到 `safe_home`，返回 `{"success": true, "message": "task1 ok"}`。
- 异常：识别为空/多目标/越界 → `success=false + message`。

#### Scenario: 多次连续调用
- **WHEN** 同一接口被连续调用 N 次（测试工具最多 3 次）
- **THEN** 每次独立执行：状态机不依赖前次成功（每次都从视觉识别开始）；同一时刻只允许一个调用执行。

### Requirement: 赛题 2（数字长方体排序摆放）
系统 SHALL 在 `POST /api/task2/execute` 触发时识别若干带数字长方体，按 `digit_blocks.placement_order_target`（默认升序）放入指定台面。

#### Scenario: 任务流程
- **WHEN** 测试工具调用赛题 2
- **THEN** 服务：
  1. `arm.look_at(staging_area)` 拍摄待取物区（坐标占位）
  2. YOLO/模板匹配识别每个长方体的数字面 → 建立 `[(block_id, digit, pick_x, pick_y, pick_z)]` 列表
  3. 按目标顺序排序
  4. 逐个 `arm.pick`（使用 `hand.pose('grasp_digit')`）→ `arm.place(slot_n)`（台面槽位来自 `digit_blocks.slots[]`，按顺序分配）
  5. 全部完成 → `safe_home` → 返回 `{"success": true, "message": "task2 ok"}`

#### Scenario: 缺失/误识别
- **WHEN** 识别数量与配置 `digit_blocks.expected_count`（占位）不一致，或存在置信度 < 阈值的识别
- **THEN** 重试一次；仍失败则 `{"success": false, "message": "digit recognition failed: got X expected Y"}`。

### Requirement: 赛题 3（形状入槽）
系统 SHALL 在 `POST /api/task3/execute` 触发时识别无贴纸多面体形状并放入对应名称的槽位，不要求固定顺序。

#### Scenario: 任务流程
- **WHEN** 测试工具调用赛题 3
- **THEN** 服务：
  1. `arm.look_at(staging_area)` 拍摄
  2. 形状分类（圆形/方形/异形）→ 返回 `[(block_id, shape_name, pick_pose)]`
  3. 对每个 `shape_name` 在 `config.shapes[].slots` 找到目标槽位
  4. `arm.pick`（`hand.pose('grasp_shape')`）→ `arm.place(slot)`
  5. 全部完成 → `safe_home` → 返回 `{"success": true, "message": "task3 ok"}`

#### Scenario: 形状-槽位不匹配
- **WHEN** 出现未在 `config.shapes` 中登记的类别
- **THEN** 跳过该目标并在 message 中记录 skipped 数量；其它仍正常完成；最终 success 以"是否全部已登记类别都完成"判定。

### Requirement: 自检与可观测
系统 SHALL 提供 `tools/selftest.py`，按以下顺序自检并打印报告：① `GET /api/health`；② 启动 mock 硬件（机械臂/灵巧手走接口示例风格回声）；③ 依次调用 task1/2/3 触发并断言返回 success。

#### Scenario: 报告输出
- **WHEN** 自检脚本执行结束
- **THEN** 输出每个接口耗时、是否通过；任一失败退出码 1，全通过 0。

---

## MODIFIED Requirements
（首次落库，无现有需求被修改。）

## REMOVED Requirements
（无。）
