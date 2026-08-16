# 01-算法服务

竞赛软件唯一对接口：监听 5000 端口的 HTTP 服务，实现 `GET /api/health` + `POST /api/task1|task2|task3/execute`。
代码来自 `TJCEIE_ZHONGKONG-main` 仓库（`algorithm_service/` + `config/` + 服务端工具）。

## 结构

- `algorithm_service/server.py` — aiohttp 服务：4 个接口、全局互斥锁（并发返回 `busy`）、异常兜底返回 `success=false`
- `algorithm_service/config.py` — `config/site.yaml` 加载；所有现场标定值走占位符 `__现场标定后填入__`，未标定时告警
- `algorithm_service/hardware/arm.py` — B9 机械臂客户端（`hardware/`，独立调试副本在 `../02-机械臂/`）
- `algorithm_service/hardware/hand.py` — O10 灵巧手客户端（独立调试副本在 `../03-灵巧手/`）
- `algorithm_service/planner/` — `safe_home/approach/pick/place` 动作库 + 安全区校验（占位/越界直接拒动）
- `algorithm_service/tasks/task1|2|3.py` — 三赛题流程骨架；`taskX_vision.py` 为视觉最小版
- `algorithm_service/vision/camera.py` — 旧视觉封装（眼在手外假设，**待被 `../04-相机/` 的眼在手上链取代**）
- `tools/service_selftest.py` — 端到端自检（in-process mock 硬件）；`tools/calibrate.py` — 人工标定录入（备选路线）

## 运行

```powershell
pip install aiohttp pyyaml numpy requests opencv-contrib-python pytesseract
python -m algorithm_service                 # 默认 0.0.0.0:5000, config/site.yaml
python tools/service_selftest.py            # 端到端自检
python tools/calibrate.py                   # 现场人工录入标定值
```

## 审查结论（2026-08-16，本机无真机）

自检 `service_selftest.py` 跑通（Overall PASS，10 项场景全过）。

已修复（仅 work 副本，仓库原件未动）：

- `tools/calibrate.py` 第 116/125 行 `float(PLACEHOLDER)` 崩溃 → 保留占位字符串；结尾 `✓` 在 GBK 控制台必崩 → `[OK]`。
- **假绿灯**：旧 selftest 吞 `PickError`、只断言"有 success 字段"，task2 识别全空也 PASS。重写为：失败路径必须 `success=false` 且 message 含预期原因；成功路径必须断言 mock 硬件收到预期动作（开关坐标、槽位坐标、手型序列）。
- **task3 裸 ValueError**：`float('__现场标定后填入__')` 直接当 message。新增 `planner.pose_from_vec3()` + `tasks/_coords.py`，未标定一律抛中文 `PickError` 指明缺哪项；手眼/内参占位时不再静默用单位矩阵解算错坐标。
- **task1 按旧"6 按钮"假设重写为真实赛制**：3 指示灯（红/黄/绿）× 每灯 1 开关（2 按钮 + 1 拨动）。配置改为 `panel.photo_pose / lamps[].roi+switch / switches[].kind+pos+act_dir+travel+standoff`；视觉改为 ROI 制 `detect_lit_lamp`（颜色比例 + 亮度兜底）；动作改为真实点按/拨动序列（接近→单指/拨动手型→压入或拨动→撤离→张手）。
- **拨杆内存状态机删除**：无状态设计（规则 5.7），拨动方向由配置 `act_dir` 固定；新增 `flick` 拨开关手型。
- 附带修出被新自检照出的旧 bug：`task3.py` 把 `_Shape` dataclass 当 tuple 解包（`cannot unpack non-iterable`）。
- 顺手同步：`calibrate.py` 面板段新 schema、`server.py` 成功 message 附带结果摘要（`lit_lamp`/`placed` 等，竞赛软件只看 success 不受影响）。

第二轮修复（2026-08-16，自检扩到 13 项场景）：

- **`errors_watch` 假监控**：后台线程抛 `HandError` 当场被线程边界吞掉，任务照常 success。改为只记录 `first_error` + 日志，三个 task 在每块前/后检查，命中即中止并撤回（8.4 真生效了）。
- **每块开一条相机管线**：`_coords.pixel_to_base_pose` 原来每个块 `Vision()` 一次（`pipeline.start()` 且从不 close）。改为纯 numpy 数学解算，不碰 SDK。
- **7.7/6.7 规则分**：task3 单块失败/掉落改为记录 `failed` 后继续分拣剩余（全灭才返回 false）；task2 抓起失败按 `grasp_retries`（默认 2，site.yaml 可配）重试，仍失败才返回 false。注意 planner 会把 ArmError 包成 PickError，捕获要带上。
- **task2 重试采帧**：彩色/深度改为同一帧。
- **OCR 两处雷**：临时 PNG 从 cv2 安装目录改到系统临时目录（工控机只读会静默全灭）；tesseract 候选 exe 必须带 `tessdata/eng.traineddata`（本机 `D:\OCR` 只有 chi_sim，曾导致识别全空）。
- task3 全部分拣失败时返回 `success=false` 并提示用第 2 次机会；部分完成返回 true 且 message 列出 `failed`。

第三轮修复（2026-08-16，来自外部代码审查报告 `代码审查-屎山排查.md`，自检扩到 15 项场景）：

- **A1 task3 全跳过也报 success**：只拦了"全失败"没拦"全跳过"（形状名与 `shapes.kinds` 对不上时一块不放也 true）→ 改为 `if not placed: raise`，附诊断提示。
- **A2 Vision 手眼占位静默退单位矩阵**：构造时矩阵非法 → `hand_eye=None`（capture 不受影响），`pixel_to_base` 直接抛 `VisionError`。docstring 写明接线约定：`t_base_end(拍照时刻) @ t_end_camera(标定输出)`，04 的求解结果不能直接填。
- **A3 task2 数量校验失效**：`expected_count` 占位转 0 后长度永不校验（识别 3 个也照放）→ 未标定直接拒动。
- **A4 task2 重拍报错数字用旧值**：报 "got 0" 实为 3 → 以两次识别中更可信的一次为准（选取规则见第四轮）。
- **B1** task1 裸 `next()` → 默认 None + 人话 PickError；**B2** 手型解析裸 `float()` → `_to_pose_list` 逐项兜底。
- 屎山清理：planner 参数 `hand_pose_table` 遮蔽同名函数 → `pose_table`；删 `look_at`/`approach` 死代码；`SAFE_HOME` 移入 `service.safe_home`（site.yaml 可改）；删 server 里 `_ = hand_pose_table` 消 lint 写法；深度取样从单像素改 5×5 中值（与 04 对齐）；selftest 的 `report.items[-1]` 事后篡改改为 `extra_ok` 参数。
- 暂不动（已记录待办）：01↔04 手眼链统一（真机接线时做）、05/06/07 与 04 的整文件副本（模块工作台定位，正式服务以 01 为准）、`str(e)` 透传、`D:\OCR` 候选（已加 eng 校验）、04 内部命名。

第四轮修复（2026-08-16，外部审查复审意见）：

- **task2 重拍选帧"更多≠更对"**：旧规则 `len(retry) > len(raw)` 会在"第一次误检 5 个、重拍正确 4 个"时丢掉正确结果。改为：恰好识别够 `expected` 的优先，都没有就选数量更接近 `expected` 的；打平保留首帧。报错数字以当选帧为准。
- **`safe_home` 半标定静默回退**：只填了部分轴时原会被当成"未配置"静默换成内置默认位（半标定坐标和默认位可能差很远）。改为只有三轴全占位才回退；部分填写抛 `PickError` 并报清是哪根轴未标定。
- **task2 报错文案去写死数量**：`expected_count` 本身可配，未标定时的提示不再写"固定 4 块"，改为"请按赛题实际块数配置"。

详细"还剩啥"见 `../进度总览.md`。
