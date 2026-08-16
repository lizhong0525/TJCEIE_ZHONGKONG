# 02-机械臂（FTArm B9，`http://<IP>:8087`）

## 文件

- `arm_client.py` — 机械臂 HTTP 客户端（与 `../01-算法服务/algorithm_service/hardware/arm.py` 同源副本，此处用于独立调试）
- `arm_bringup.py` — 开机自检脚本，对应任务清单第 2 部分的顺序：
  `status → controllers → motors → enable → enabled 确认 → pose → plan_only 预览 →（--move 才做真实微动）`
- `test_arm_client_offline.py` — 离线测试（stdlib 假 B9 服务），无需真机

## 用法

```powershell
python test_arm_client_offline.py                      # 离线验证客户端
python arm_bringup.py --host 192.168.1.100             # 只读检查 + 使能 + plan_only
python arm_bringup.py --host 192.168.1.100 --move      # 加真实微动（先清空臂下区域）
```

## 关键备忘（来自官方文档，写代码前必看）

- 目标位姿必须嵌套：`{"mode":"right_arm","right":{"x":..,"roll":..,...}}`；左臂工作区换 `left_arm`/`left`
- 推荐姿态 `roll=-3.141, pitch=-1.552, yaw=3.141`；直线安全工作域（右臂）Y −0.28~−0.04 m、Z 0.44~0.52 m
- REST 运动接口阻塞，服务器上限 60s，客户端 timeout ≥90s
- `message` 含 `OMPL` = 直线回退成自由路径——**`arm_client.py` 只告警不抛错**，业务层要自己检查
- 业务失败返回 HTTP 400，客户端抛 `ArmError`（原始 message 嵌在异常文本里）
- `POST /api/disable` 会掉臂；`/api/cancel` 只是软标记停不了轨迹

## 审查结论（2026-08-16，本机无真机）

离线 mock 测试 11 项全过：状态/位姿/使能解析、直线/plan_only、不可达抛错、OMPL 仅告警、joints 参数校验。
未验证（要真机）：真实 `message` 文本是否与文档一致、60s 上限行为、TF 就绪前 `pose=null` 的等待逻辑、WebSocket 进度推送（客户端未实现，初版不需要）。
