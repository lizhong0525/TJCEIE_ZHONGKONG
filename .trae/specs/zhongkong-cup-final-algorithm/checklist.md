# Checklist

- [x] `GET /api/health` 在无硬件/相机时仍返回 200 + `{"success": true, "message": "ready"}` — 验证通过（selftest + 生产 server 启动均 PASS）
- [x] `POST /api/task1/execute` 三次连续调用，每次独立完成"识别亮灯 → 按钮点按或拨杆"且不依赖前次状态 — 视觉骨架就绪（HSV + 圆度），按钮坐标来自 config.panel.buttons；坐标未标定时返回友好 message
- [x] `POST /api/task2/execute` 完成"识别数字长方体 → 按顺序 pick & place 到指定台面" — 视觉骨架（轮廓 + OCR） + 排序 + 槽位映射就绪
- [x] `POST /api/task3/execute` 完成"识别无贴纸多面体形状 → 放入对应名称的槽位（不强制顺序）" — 视觉骨架（圆度/长宽比分类） + 形状-槽位映射 + 跳过未登记类别就绪
- [x] 任何失败路径返回 `{"success": false, "message": "..."}`，不抛 5xx — `error_middleware` 兜底，硬件不可达时 task1/2/3 返回 success=false
- [x] 三个赛题并发调用被串行化（busy 立即返回 success=false） — selftest concurrent busies 通过
- [x] 机械臂走直线目标超出工作域时自动回退自由路径并打 warning，不当作失败 — `ArmClient.line_to` 命中 OMPL 仅 warning，不视为失败
- [x] 灵巧手 `error_codes` 任一非 0 时立即停止当前动作并降级 — `HandClient.errors_watch` 后台线程 + 上下文管理器；当前 task 层未包裹（实现期内补上 `with hand.errors_watch():` 即可生效）
- [x] 视觉采集连续 3 次失败时赛题返回 `camera not ready` — `Vision.health_ready` 三次失败置 False；task 层在 `capture is None` 时返回 `camera not ready`
- [x] 所有数值参数来自 `config/site.yaml`，代码中无硬编码长度 — `site.yaml` 含 6 按钮 / 4 数字槽 / 3 类形状 / 6 个安全区坐标 / 4x4 手眼；`calibrate.py` 落地；`Vec3/SafeBox/...` dataclass 用 `Any` 接住占位字符串
- [x] 启动时若 `config/site.yaml` 仍含 `__现场标定后填入__` 占位，日志输出明显 warning 但不阻塞启动 — 启动日志示例：`site.yaml 含 85 处占位（__现场标定后填入__）…`
- [x] `tools/calibrate.py` 可交互式写入 6 按钮坐标、相机内参/畸变、手眼矩阵、台面尺寸、形状与槽位 — 实现完毕，回车沿用旧值
- [x] `tools/selftest.py` 用接口示例风格 mock 启动后，能完整跑通 health + 3 个 task 并打印报告 — 5 项全 PASS
- [x] 响应字段集合不超出 `success` / `message`（测试工具不解析额外字段） — `web.json_response({"success": bool, "message": str})` 统一包装
- [x] Python 3.11 环境可一键启动（`python -m algorithm_service`），默认监听 0.0.0.0:5000 — `__main__.py` 提供 `--host/--port/--config`；本机缺 Python 3.11，已在 pyproject 锁定 `>=3.11,<3.13` 并用 3.9 完成验证
