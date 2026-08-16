# team02 工程对比参考清单（2026-08-16）

> 对比对象：`G:\中控杯\0816\team02_zhongkongbei-main\zhongkongbei-main\`（他队工程）
> 对比基准：`G:\中控杯\0816\work\`（我方工程）
> 总体结论：**team02 是工程组织模板 + 接口骨架，三个任务全是 dry-run stub，无可参考的实现**；值得参考的只有 3 个增量点（见清单 A）。

---

## A. 可参考清单（建议行动）

| # | 参考项 | 来源文件 | 我方现状 | 价值 | 建议 |
|---|--------|----------|----------|------|------|
| A1 | **结构化 JSONL 请求日志**（每日 `logs/YYYYMMDD.jsonl`，记录 time/task/message/path/success/elapsed_ms，现场排障看它） | team02 `app/context.py` 的 `RuntimeContext.log()` | 仅 Python logging，无每日请求流水 | 高：现场排障价值大 | 在 `01-算法服务/server.py` 中间件加几行，小改动 |
| A2 | **`GET /api/config/summary` 调试端点**（返回 dryRun / arm 地址 / hand 地址 / 相机 / logDir，现场一眼确认状态） | team02 `app/server.py` do_GET | 无此端点（健康检查不返回配置摘要） | 中：现场调试省事 | 新增端点，不违反官方 4 接口契约 |
| A3 | **现场调试 11 步顺序清单**（health → 臂 8087 → 手 8088 → 臂 status/motors/enable → 手 open/half/grip/release → 相机取图 → 标定 → 任务2 单块 → 完整链路；优先级 任务2 > 任务1 > 任务3） | team02 `README.md` §9 | 进度总览有等价内容但未成清单 | 中：防止现场乱序 | 对照补一份现场调试清单 |

---

## B. 逐项对比清单

### B1. 接口契约
- [x] 两边一致：`GET /api/health` + `POST /api/task1|2|3/execute`，JSON `{success, message}`
- 我方更优：aiohttp + 互斥锁（并发返回 busy）+ 异常兜底中间件 + 成功 message 带结果摘要
- team02：stdlib `ThreadingHTTPServer`，无锁无兜底摘要

### B2. 任务实现（team02 无可参考）
- team02 三个 task 全部为 stub：`return True, "taskX dry-run ok"` / `return False, "taskX not implemented"`
- 我方已实现：task1 点按/拨动序列、task2 数字排序搬运（重拍选帧 + grasp_retries）、task3 分拣（单块失败继续）
- **结论：碾压级差距，无参考价值**

### B3. 配置体系
- team02：扁平 JSON + `dry_run` 开关
- 我方：YAML + `__现场标定后填入__` 占位校验 + 类型化 dataclass + safe_box 安全区 + 手眼矩阵 t_end_camera，未标定拒动
- **我方更强，无需参考**

### B4. 视觉链
- team02：相机 stub（`"camera capture is not implemented yet"`）
- 我方：Gemini335 全链（内参导出 → 手眼标定带门禁 → verify_known_point 验收 → 三赛题视觉 + 合成测试 6+5+5）
- **我方更强，无需参考**

### B5. Mock / 自检
- 两边 mock 同源（413 vs 418 行，差异仅为空 body 对齐 BUG-4）
- 我方另有：25 项端到端自检 + 02/03 离线测试（11/11、9/9）
- **我方更强，无需参考**

### B6. 手型预设
- team02：open / half / box_grip / press（4 个）
- 我方：open / close / grasp_digit / grasp_shape / tap / flick（6 个，更贴合三赛题）
- **我方更强，无需参考**

### B7. 硬件 API 文档
- team02 携带的臂/手 API 文档我方已有：`G:\中控杯\0816\FTArm 580-B9机械臂接口文档\`、`G:\中控杯\0816\灵巧手接口文档\`
- **无增量**

### B8. 安全红线
- 两边一致：低速 ≤0.08、OMPL 告警、堵转保护、物理急停优先
- **无增量**

---

## C. 结论

1. **无需参考的实现部分**：B2 任务、B3 配置、B4 视觉、B5 自检、B6 手型 —— 我方已全面超越。
2. **建议落实的 3 个增量**：A1 请求 JSONL 日志、A2 /api/config/summary 端点、A3 现场调试 11 步清单。
3. **后续行动**：待确认后把 A1/A2 落进 `01-算法服务/`（小改动，不动接口契约），A3 补一份 `现场调试清单.md`。
