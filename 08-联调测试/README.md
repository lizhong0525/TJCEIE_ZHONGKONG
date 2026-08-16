# 08-联调测试

## 文件

- `contestant_mock_server.py` — 官方接口示例模拟器（拷贝自 `../接口示例/`），行为即竞赛软件期望的接口契约

## 对接验收步骤（对应任务清单第 1.2 / 第 8 部分）

1. 启动 mock：`python contestant_mock_server.py`（默认 127.0.0.1:5000）
2. 打开 `../../测试工具/ZhongkongCup.AlgorithmTester.exe`，Base URL 填 `http://127.0.0.1:5000`
3. 依次点健康检查、赛题 1/2/3，确认全显示成功
4. 失败路径：`python contestant_mock_server.py --task2-mode failure`，确认软件显示失败
5. **耗时容忍度（重要，决定真机节奏）**：`--task1-delay 8` 起步，再试 60、120 秒，测出竞赛软件有没有硬超时
6. 把 mock 换成 `../01-算法服务/` 的真服务（`python -m algorithm_service`），重复 3–5
7. 赛前彩排：用测试工具完整跑 3 个 task 各 2 遍（演示时每项至多 2 次机会）

mock 常用参数：`--taskX-mode success|failure|http-error|invalid-json|empty`、`--taskX-delay 秒`、`--port 端口`。

## 审查结论（2026-08-16）

拷贝后实跑验证：`GET /api/health`、`POST /api/task1/execute`、`POST /api/task2/execute` 均返回 `{"success":true,...}` ✓

**2026-08-16 晚补充**：`POST /api/task3/execute` 实跑 success ✓（此前漏验）；修 BUG-4——空 body（`Content-Type: application/json` 但无内容）原来 400，与 01 真服务（按 `{}` 放行）行为不一致，已对齐，实测空 body 返回 200 success。注意此修改只在本副本，`../../接口示例/` 的官方原版未动。

## 还剩

- 第 5 步的软件超时实测（要开着 WPF 测试工具手动点）
- 真服务替换 mock 后的全流程验收
