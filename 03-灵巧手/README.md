# 03-灵巧手（O10，`http://<IP>:8088`）

## 文件

- `hand_client.py` — 灵巧手 HTTP 客户端（与 `../01-算法服务/algorithm_service/hardware/hand.py` 同源副本，此处用于独立调试）
- `hand_bringup.py` — 开机自检 + **0/1 方向验证**（任务清单 3.3：文档 §3.1 与 §4.6 互相矛盾，必须真机确认一次）
- `test_hand_client_offline.py` — 离线测试（stdlib 假 O10 服务）

手型数据的**唯一来源**是 `../01-算法服务/config/site.yaml` 的 `hand.poses`（原 `poses.yaml`
副本已删，消灭三处同步靠自觉的问题）；bringup 标定结论直接往那里写。

## 用法

```powershell
python test_hand_client_offline.py            # 离线验证客户端
python hand_bringup.py --host 192.168.1.100   # 真机自检 + 方向验证（需要人眼观察）
```

## 关键备忘

- 控制只用 `POST /api/set_pos`（10 维 [0,1]）；**不要用 `/api/set_motor` 极限值**（堵转）
- 关节顺序（索引 0–9）：thumb_roll / thumb_abad / thumb_mcp / index_abad / index_pip / middle_pip / ring_abad / ring_pip / pinky_abad / pinky_pip
- 错误码 bitmask：1 堵转 / 2 过热 / 4 过流 / 8 电机异常 / 16 通讯异常；非 0 立即停手
- `hand_client.errors_watch()` 后台每 200ms 拉 `/api/errors`，非 0 触发回调（已在离线测试验证）
- 抓取确认思路（清单 3.6）：夹持后轮询 `/api/pvc` 看电流——电流升高但位置没到=夹到了；位置到底电流没起=抓空
- 进阶：`POST /api/set_pvc` 带 `torque`（mA, 0–1000）做位置+电流混合控制，防夹坏道具

## 审查结论（2026-08-16，本机无真机）

离线 mock 测试 9 项全过：状态/位置/错误码解析、set_pos 双向校验、pose_name 手型表、错误监控触发。
未验证（要真机）：**0/1 与张手/握拳的对应关系**（bringup 脚本第 3 步就是干这个的）、实际手型参数、`set_pvc` 限流效果、SDK 串行执行行为。
