# To-Do List：操作台尺寸由视觉识别完成

> 背景：官方图纸不给任何尺寸（台面、按钮、槽位全未知），规则要求"选手算法服务必须
> 自行完成视觉识别、运动规划、抓取放置等逻辑"。
>
> 策略：
> - **主路线**：视觉自动标定（相机 + 深度算出按钮/槽位/台面坐标）
> - **备路线**：人工量测录入（`python -m tools.calibrate`），视觉跑不通时兜底
> - **交叉校验**：两路线结果对比，偏差超阈值拒绝写盘并报警
> - **阈值**：`config/site.yaml` → `calibration.cross_check_tol`，默认 0.005 m（5 mm），
>   现场可改，改完重启服务生效。详见 `docs/现场标定说明.md`
> - **safe_box**：只走人工录入，不信视觉

> 2026-08-12 相机模块并入：根目录新增顶层 `vision/` 包（Gemini335 采集+D2C对齐、
> 内参导出、**眼在手上**手眼标定、台面 RANSAC 拟合、三赛题视觉入口）和配套
> `tools/` 脚本、`.bat` 启动器、根目录 `config.example.json`。详见 `README.md` 与
> `使用说明.md`。注意：新模块用根目录 `config.json` + `results/*.json`，与主项目
> `config/site.yaml` 是**双轨配置**，映射层未接线前视觉结果不得用于真机运动。
> 原服务端到端自检改名为 `python -m tools.service_selftest`（`tools/selftest.py`
> 现为相机模块离线自检）。

## 已完成

- [x] HTTP 服务骨架：`/api/health` + task1/2/3 三接口、并发互斥返回 `busy`（`algorithm_service/server.py`）
- [x] 配置体系：`config/site.yaml` 占位 + 加载告警 + 安全区/占位拦截（`algorithm_service/config.py`）——视觉与人工两条路线的统一出口
- [x] 视觉底座：`Vision` 采集 + `pixel_to_base` 手眼变换（`algorithm_service/vision/camera.py`，眼在手外假设，待被新 `vision/` 取代）
- [x] 三赛题流程骨架：识别→规划→执行→复位（`algorithm_service/tasks/task1/2/3.py`）
- [x] 规划器：`safe_home/approach/pick/place` + 安全区校验（`algorithm_service/planner/__init__.py`）
- [x] 赛题 1 亮灯检测最小版：HSV + 圆度 + 面积（`algorithm_service/tasks/task1_vision.py`）
- [x] 赛题 2 数字块检测 + tesseract OCR 最小版（`algorithm_service/tasks/task2_vision.py`）
- [x] 赛题 3 形状分类最小版：圆度/长宽比（`algorithm_service/tasks/task3_vision.py`）
- [x] 人工标定录入工具 `tools/calibrate.py`（定为备选路线，保留）
- [x] 端到端自检 `python -m tools.service_selftest` 可跑（Overall PASS；有假绿灯，见"修已有坑"）
- [x] 交叉校验阈值定为 5 mm：配置项 `calibration.cross_check_tol` 已就位，文档见 `docs/现场标定说明.md`
- [x] 相机模块并入（2026-08-12）：顶层 `vision/` 包 + 标定工具链全部就位，离线自检 `python tools/selftest.py` PASS

## 待办 · 视觉标定链（主路线，工具已就位，待真机执行）

- [ ] A   相机内参：真机跑 `python tools/export_intrinsics.py` → `results/intrinsics.json`（工具已就位）
- [ ] A   手眼标定（眼在手上）：真机跑 `tools/collect_hand_eye.py` 采样 ≥12 组 → `tools/solve_hand_eye.py` 求解 `T_end_camera`，质量门禁必须通过（工具已就位）
- [ ] 台面平面识别：真机跑 `python tools/fit_table_plane.py` → `results/table_plane_camera.json`（RANSAC，工具已就位）
- [ ] 控制面板按钮/灯视觉定位：新 `vision/task1.py` ROI 亮度法，真机跑 `tools/test_task1_lamp.py` 调阈值；赛题 1 实为 3 灯 + 2 按钮 + 1 拨杆，机械动作以预设动作+视觉测偏移为主体
- [ ] 赛题 2：staging 区 + 4 个放置槽位视觉识别（`vision/task2.py` 仅为初版入口，需现场图像集迭代）
- [ ] 赛题 3：4 个物体 + 4 个槽位视觉识别（`vision/task3.py` 仅为初版入口，需三维姿态/遮挡处理）
- [ ] **接线（关键）**：`results/*.json` → `config/site.yaml` 字段映射与交叉校验写盘；`algorithm_service` 运行时改用新 `vision/` 的眼在手上链（`T_base_end × T_end_camera`），替换旧 `Vision` 封装。完成前视觉结果不得用于真机运动

## 待办 · 备选路线补强（人工）

- [ ] `tools/calibrate.py` 补半自动辅助：量一个点就用视觉显示当前像素 + 深度，减少人工读数误差（可用新 `tools/check_camera.py` 的中心深度显示）
- [ ] 打印版现场速查表：开赛后要量的尺寸清单 + 顺序（图纸无尺寸，全靠自己量）

## 待办 · 交叉校验（两路线汇合处）

- [ ] 视觉标定 vs 人工测量（或视觉两次互测）偏差校验，超 `calibration.cross_check_tol` 拒绝写盘并报警（读配置，不许写死）
- [ ] `safe_box` 人工录入一次（安全相关，不走视觉）

## 待办 · 修已有坑

- [ ] 修自检假绿灯：`tools/service_selftest.py` mock 的 `_t2`/`_t3` 吞 `PickError`，识别全空也返回 `success=true`（已实跑复现）；验收加一条"识别全空必须 success=false"
- [ ] 修 `task2_vision.py` / `task3_vision.py` 每识别一个目标就 new 一个 `Vision`（重复初始化相机 SDK），改为注入共享实例
- [ ] 修 task3 占位坐标抛裸 `ValueError: could not convert string`（自检日志实锤），改友好 `PickError`
- [ ] 拨杆 toggle 真实动作规划（现为内存状态 + 复用按钮坐标 push 的占位实现）

## 待办 · 现场验收

- [ ] 真机跑视觉标定全流程，出误差报告（测距/重投影误差 ≤ `cross_check_tol`）；验收标准见 `使用说明.md` 第 14 节
- [ ] 视觉路线与人工路线各标定一次，对比确认交叉校验生效
- [ ] 三赛题真机联调（覆盖赛题 1 连调 3 次的赛制）
- [ ] 用 `测试工具/ZhongkongCup.AlgorithmTester.exe` 全流程验收
- [ ] 回归：`service_selftest` 全 PASS 且无假绿灯，标定后 `site.yaml` 零占位
