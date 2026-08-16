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

详细"还剩啥"见 `../进度总览.md`。
