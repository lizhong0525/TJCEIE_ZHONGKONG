# O10 灵巧手远程控制 API 参考手册

> **服务组件**：`o10_server.py`（Python + aiohttp，桥接 AgiLink OmniHand SDK）
> **协议**：HTTP/1.1 · WebSocket　**数据格式**：JSON (UTF-8)　**鉴权**：无（见安全建议）

---

## 目录

- [1. 概述](#1-概述)
- [2. 通用约定](#2-通用约定)
- [3. 数据字典](#3-数据字典)
- [4. REST 接口详解](#4-rest-接口详解)
  - [4.1 GET /api/status — 完整设备状态](#41-get-apistatus--完整设备状态)
  - [4.2 GET /api/pose — 归一化位置](#42-get-apipose--归一化位置)
  - [4.3 GET /api/pvc — 弧度/速度/电流](#43-get-apipvc--弧度速度电流)
  - [4.4 GET /api/config — 设备配置](#44-get-apiconfig--设备配置)
  - [4.5 GET /api/errors — 错误码](#45-get-apierrors--错误码)
  - [4.6 POST /api/set_pos — 归一化位置控制](#46-post-apiset_pos--归一化位置控制)
  - [4.7 POST /api/set_pvc — 弧度/速度/电流控制](#47-post-apiset_pvc--弧度速度电流控制)
  - [4.8 POST /api/set_motor — 电机位置控制](#48-post-apiset_motor--电机位置控制)
  - [4.9 GET / — 网页控制面板](#49-get----网页控制面板)
- [5. WebSocket 接口详解](#5-websocket-接口详解)
- [6. 客户端参考实现](#6-客户端参考实现)
- [7. 接口支持列表](#7-接口支持列表)
- [8. 安全建议](#8-安全建议)

---

## 1. 概述

O10 远程控制 API 将 AgiLink OmniHand 2025 (O10) 10 自由度灵巧手的 SDK 桥接为 HTTP/WebSocket 协议，使**任意系统**（Windows / macOS / Linux / iOS / Android）的外部设备都能通过网络控制 O10 灵巧手。

| 能力 | REST | WebSocket | 说明 |
|---|---|---|---|
| 归一化位置控制 | POST /api/set_pos | set_pos | 0-1 归一化，10 自由度 |
| 弧度/速度/电流控制 | POST /api/set_pvc | set_pvc | 弧度空间直接控制 |
| 电机位置控制 | POST /api/set_motor | set_motor | 原始电机位置 0-4096 |
| 设备状态查询 | GET /api/status | status | 位置/弧度/电机位置/速度/电流/错误码 |
| 归一化位置查询 | GET /api/pose | pose | 仅归一化位置 |
| PVC 查询 | GET /api/pvc | pvc | 仅弧度/速度/电流 |
| 设备配置 | GET /api/config | config | 型号/SN/固件版本/电压 |
| 错误码 | GET /api/errors | errors | 10 关节错误码 bitmask |
| 实时状态推送 | — | 自动 50ms 推送 | WebSocket 连接即推送 |
| 网页控制面板 | GET / | — | 免开发即用 |

### 服务地址

| 通道 | 默认地址 | 说明 |
|---|---|---|
| HTTP | `http://<主机IP>:8088` | 默认端口 |
| WebSocket | `ws://<主机IP>:8088/ws` | 同端口 /ws 路径 |
| 控制面板 | `http://<主机IP>:8088/` | 浏览器直接打开 |

---

## 2. 通用约定

### 2.1 请求与响应规范

- **请求头**：`Content-Type: application/json`（POST 请求必须）
- **GET** 请求无参数，**POST** 请求体为 JSON 对象
- **JSON 格式**：字段名区分大小写，布尔用 `true/false`

| HTTP 状态 | 含义 |
|---|---|
| 200 | 业务成功（`success: true`） |
| 400 | 业务失败（`success: false`，见 `message` 字段） |
| 500 | 服务器内部错误 |

### 2.2 通用响应体

```json
{
  "success": true,
  "message": "描述信息"
}
```

- `success` (bool)：业务是否成功
- `message` (string)：成功描述或失败原因
- 成功时可能包含额外字段（见各接口）

### 2.3 并发与线程安全

- 所有 SDK 调用在单线程池中串行执行，天然互斥
- 多客户端同时控制：遵循后发先至原则，**请在业务层保证单一控制方**
- 所有操作在 executor 中执行，无硬超时（依赖 SDK 内部超时机制）

---

## 3. 数据字典

### 3.1 关节索引（10 自由度）

| 索引 | 关节名 | 中文名 | 右手弧度范围 | 归一化范围 |
|------|--------|--------|-------------|-----------|
| 0 | thumb_roll | 拇指旋转 | -0.03 – 1.12 rad | 0 – 1 |
| 1 | thumb_abad | 拇指外展 | -1.64 – 0.05 rad | 0 – 1 |
| 2 | thumb_mcp | 拇指弯曲 | 0.0 – 0.84 rad | 0 – 1 |
| 3 | index_abad | 食指侧摆 | -0.16 – 0.0 rad | 0 – 1 |
| 4 | index_pip | 食指弯曲 | 0.0 – 1.48 rad | 0 – 1 |
| 5 | middle_pip | 中指弯曲 | 0.0 – 1.48 rad | 0 – 1 |
| 6 | ring_abad | 无名指侧摆 | 0.0 – 0.17 rad | 0 – 1 |
| 7 | ring_pip | 无名指弯曲 | 0.0 – 1.48 rad | 0 – 1 |
| 8 | pinky_abad | 小指侧摆 | 0.0 – 0.19 rad | 0 – 1 |
| 9 | pinky_pip | 小指弯曲 | 0.0 – 1.48 rad | 0 – 1 |

- **归一化 0** ≈ 关节最小角度（伸展/张开）
- **归一化 1** ≈ 关节最大角度（弯曲/闭合）
- **电机位置范围**：0 – 4096（原始编码器值）
- 左手关节范围与右手呈镜像关系（服务器根据手型自动处理）

### 3.2 错误码 bitmask（5 位）

| Bit | 值 | 含义 |
|-----|---|------|
| 0 | 1 | 堵转 (stalled) |
| 1 | 2 | 过热 (overheat) |
| 2 | 4 | 过流 (over_current) |
| 3 | 8 | 电机异常 (motor_except) |
| 4 | 16 | 通讯异常 (commu_except) |

多个错误同时存在时 bitmask 叠加。例如：堵转(1) + 过热(2) = 错误码 3。

### 3.3 设备命名

| 设备 | `name` | 说明 |
|------|--------|------|
| O10 左手 | `omnihand_o10` | `hand_type: "left"` |
| O10 右手 | `omnihand_o10` | `hand_type: "right"` |

---

## 4. REST 接口详解

> 每个接口给出：接口定义 → 请求参数 → 返回参数 → curl 示例 → Python 示例 → 返回示例 → 注意事项。

### 4.1 GET /api/status — 完整设备状态 ★

返回设备的全部运行时状态：连接信息、归一化位置、弧度位置、电机位置、速度、电流、错误码。

| 项 | 值 |
|---|---|
| 请求方式 | `GET` |
| 接口地址 | `/api/status` |
| 描述 | 一次性获取所有状态数据 |

**返回参数**

| 字段 | 类型 | 说明 |
|---|---|---|
| connected | bool | SDK 是否已连接设备 |
| hand_type | string | 手型（`left` / `right`） |
| name | string | 设备名（`omnihand_o10`） |
| model | string | 产品型号 |
| sn | string | 序列号 |
| hardware_ver | string | 硬件版本 |
| software_ver | string | 固件版本 |
| dof | int | 自由度（10） |
| timestamp | float | 服务器时间戳（Unix 秒） |
| position | float[10] | 归一化位置 (0-1) |
| joint_rad | float[10] | 关节弧度 (rad) |
| motor_position | int[10] | 电机位置 (0-4096) |
| velocity | int[10] | 关节速度 |
| current | int[10] | 电机电流 |
| error_codes | int[10] | 错误码 bitmask（0=正常） |
| joint_names | string[10] | 关节英文名 |
| joint_names_cn | string[10] | 关节中文名 |

```bash
curl http://192.168.1.100:8088/api/status
```

```python
import requests
r = requests.get("http://192.168.1.100:8088/api/status", timeout=5).json()
print(f"手型: {r['hand_type']}, 位置: {r['position']}")
```

**返回示例**

```json
{
  "connected": true,
  "hand_type": "left",
  "name": "omnihand_o10",
  "model": "OmniHand 2025",
  "sn": "O10XXXXXXXXXX",
  "hardware_ver": "1.0.0",
  "software_ver": "1.2.0",
  "dof": 10,
  "timestamp": 1784697264.38,
  "position": [0.50, 0.48, 0.95, 0.10, 0.85, 0.85, 0.05, 0.85, 0.05, 0.85],
  "joint_rad": [0.545, -0.828, 0.798, -0.144, 1.258, 1.258, 0.008, 1.258, 0.010, 1.258],
  "motor_position": [2000, 2100, 3800, 500, 3500, 3500, 200, 3500, 150, 3500],
  "velocity": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "current": [120, 80, 150, 90, 200, 200, 70, 200, 60, 200],
  "error_codes": [0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
  "joint_names": ["thumb_roll", "thumb_abad", "thumb_mcp", "index_abad", "index_pip", "middle_pip", "ring_abad", "ring_pip", "pinky_abad", "pinky_pip"],
  "joint_names_cn": ["拇指旋转", "拇指外展", "拇指弯曲", "食指侧摆", "食指弯曲", "中指弯曲", "无名指侧摆", "无名指弯曲", "小指侧摆", "小指弯曲"]
}
```

> 示例中 `error_codes[2] = 1` 表示关节 2（拇指弯曲）发生堵转。

---

### 4.2 GET /api/pose — 归一化位置

仅返回归一化位置，比 `/api/status` 轻量。

| 项 | 值 |
|---|---|
| 请求方式 | `GET` |
| 接口地址 | `/api/pose` |

**返回参数**

| 字段 | 类型 | 说明 |
|---|---|---|
| success | bool | |
| position | float[10] | 归一化位置 0-1 |
| joint_names | string[10] | 关节英文名 |
| joint_names_cn | string[10] | 关节中文名 |

```bash
curl http://192.168.1.100:8088/api/pose
```

**返回示例**

```json
{
  "success": true,
  "position": [0.50, 0.48, 0.95, 0.10, 0.85, 0.85, 0.05, 0.85, 0.05, 0.85],
  "joint_names": ["thumb_roll", "thumb_abad", "thumb_mcp", "index_abad", "index_pip", "middle_pip", "ring_abad", "ring_pip", "pinky_abad", "pinky_pip"],
  "joint_names_cn": ["拇指旋转", "拇指外展", "拇指弯曲", "食指侧摆", "食指弯曲", "中指弯曲", "无名指侧摆", "无名指弯曲", "小指侧摆", "小指弯曲"]
}
```

---

### 4.3 GET /api/pvc — 弧度/速度/电流

返回弧度空间的关节状态。

| 项 | 值 |
|---|---|
| 请求方式 | `GET` |
| 接口地址 | `/api/pvc` |

**返回参数**

| 字段 | 类型 | 单位 |
|---|---|---|
| success | bool | |
| position_rad | float[10] | rad |
| velocity | int[10] | |
| current | int[10] | |
| joint_names | string[10] | |

```bash
curl http://192.168.1.100:8088/api/pvc
```

**返回示例**

```json
{
  "success": true,
  "position_rad": [0.545, -0.828, 0.798, -0.144, 1.258, 1.258, 0.008, 1.258, 0.010, 1.258],
  "velocity": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "current": [120, 80, 150, 90, 200, 200, 70, 200, 60, 200],
  "joint_names": ["thumb_roll", "thumb_abad", "thumb_mcp", "index_abad", "index_pip", "middle_pip", "ring_abad", "ring_pip", "pinky_abad", "pinky_pip"]
}
```

---

### 4.4 GET /api/config — 设备配置

获取灵巧手的硬件配置信息。

| 项 | 值 |
|---|---|
| 请求方式 | `GET` |
| 接口地址 | `/api/config` |

**返回参数**

| 字段 | 类型 | 说明 |
|---|---|---|
| success | bool | |
| name | string | 设备名 |
| model | string | 产品型号 |
| sn | string | 序列号 |
| hardware_ver | string | 硬件 PCB 版本 |
| software_ver | string | 驱动固件版本 |
| voltage_mv | int | 供电电压 (mV) |
| dof | int | 自由度 |
| hand_type | string | 手型 (`left` / `right`) |
| hand_device_id | int | CAN 总线设备 ID |

```bash
curl http://192.168.1.100:8088/api/config
```

**返回示例**

```json
{
  "success": true,
  "name": "omnihand_o10",
  "model": "OmniHand 2025",
  "sn": "O10XXXXXXXXXX",
  "hardware_ver": "1.0.0",
  "software_ver": "1.2.0",
  "voltage_mv": 24000,
  "dof": 10,
  "hand_type": "left",
  "hand_device_id": 1
}
```

---

### 4.5 GET /api/errors — 错误码

获取所有关节的错误码。每个关节返回 5 位 bitmask 及中文解析。

| 项 | 值 |
|---|---|
| 请求方式 | `GET` |
| 接口地址 | `/api/errors` |

**返回参数**

| 字段 | 类型 | 说明 |
|---|---|---|
| success | bool | |
| error_codes | int[10] | 每个关节的 bitmask 错误码 |
| error_details | object[10] | 每个关节的错误详情（含 `joint_index`, `joint_name`, `code`, `flags`, `has_error`） |

```bash
curl http://192.168.1.100:8088/api/errors
```

**返回示例**

```json
{
  "success": true,
  "error_codes": [0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
  "error_details": [
    {"joint_index": 0, "joint_name": "thumb_roll",  "code": 0, "flags": [], "has_error": false},
    {"joint_index": 1, "joint_name": "thumb_abad",  "code": 0, "flags": [], "has_error": false},
    {"joint_index": 2, "joint_name": "thumb_mcp",   "code": 1, "flags": ["堵转"], "has_error": true},
    {"joint_index": 3, "joint_name": "index_abad",  "code": 0, "flags": [], "has_error": false},
    {"joint_index": 4, "joint_name": "index_pip",   "code": 0, "flags": [], "has_error": false},
    {"joint_index": 5, "joint_name": "middle_pip",  "code": 0, "flags": [], "has_error": false},
    {"joint_index": 6, "joint_name": "ring_abad",   "code": 0, "flags": [], "has_error": false},
    {"joint_index": 7, "joint_name": "ring_pip",    "code": 0, "flags": [], "has_error": false},
    {"joint_index": 8, "joint_name": "pinky_abad",  "code": 0, "flags": [], "has_error": false},
    {"joint_index": 9, "joint_name": "pinky_pip",   "code": 0, "flags": [], "has_error": false}
  ]
}
```

---

### 4.6 POST /api/set_pos — 归一化位置控制 ★

设置 10 个关节的目标归一化位置 [0-1]。

| 项 | 值 |
|---|---|
| 请求方式 | `POST` |
| 接口地址 | `/api/set_pos` |
| 描述 | 阻塞式，设置完成即返回 |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| position | float[10] | **是** | 归一化目标位置，每个值 [0, 1] |

**返回参数**

| 字段 | 类型 | 说明 |
|---|---|---|
| success | bool | |
| message | string | 结果描述 |
| target | float[10] | 已设置的目标值（仅成功时） |
| joint_rad | float[10] | 换算后的目标弧度值 |

```bash
# 张手
curl -X POST http://192.168.1.100:8088/api/set_pos \
  -H 'Content-Type: application/json' \
  -d '{"position":[1,1,1,1,1,1,1,1,1,1]}'

# 握拳
curl -X POST http://192.168.1.100:8088/api/set_pos \
  -H 'Content-Type: application/json' \
  -d '{"position":[0,0,0,0,0,0,0,0,0,0]}'

# 半开
curl -X POST http://192.168.1.100:8088/api/set_pos \
  -H 'Content-Type: application/json' \
  -d '{"position":[0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5]}'

# 单独控制某几个手指
curl -X POST http://192.168.1.100:8088/api/set_pos \
  -H 'Content-Type: application/json' \
  -d '{"position":[0.5,0.5,0.0,0.5,0.0,0.0,0.5,0.0,0.5,0.0]}'
```

```python
import requests
B = "http://192.168.1.100:8088"

def set_pos(pos):
    r = requests.post(f"{B}/api/set_pos",
        json={"position": pos}, timeout=10).json()
    assert r["success"], r["message"]
    return r

# 张手
set_pos([1, 1, 1, 1, 1, 1, 1, 1, 1, 1])
# 握拳
set_pos([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
```

**返回示例**

```json
{
  "success": true,
  "message": "位置设置成功",
  "target": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
  "joint_rad": [0.545, -0.795, 0.420, -0.080, 0.740, 0.740, 0.085, 0.740, 0.095, 0.740]
}
```

**失败响应**

```json
{"success": false, "message": "需要 10 个值 (0-1), 实际收到 5"}
{"success": false, "message": "所有值必须在 [0, 1] 范围内"}
{"success": false, "message": "设备未连接"}
```

---

### 4.7 POST /api/set_pvc — 弧度/速度/电流控制

在弧度空间中直接控制关节位置。适合需要精确弧度控制的场景。

| 项 | 值 |
|---|---|
| 请求方式 | `POST` |
| 接口地址 | `/api/set_pvc` |

**请求参数**

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| position_rad | float[10] | **是** | — | 目标弧度，见 §3.1 范围 |
| torque | int[10] | 否 | `null` | 电流前馈 (mA, 0–1000)。传入非零值时启用位置+电流混合控制模式 |

> **注意**：O10 不支持独立速度控制，`torque` 字段为 mA 单位（0–1000），非标准 N·m。

```bash
# 全关（最小弧度，握拳）
curl -X POST http://192.168.1.100:8088/api/set_pvc \
  -H 'Content-Type: application/json' \
  -d '{"position_rad":[-0.03,-1.64,0.0,-0.16,0.0,0.0,0.0,0.0,0.0,0.0]}'

# 全开（最大弧度，张手）
curl -X POST http://192.168.1.100:8088/api/set_pvc \
  -H 'Content-Type: application/json' \
  -d '{"position_rad":[1.12,0.05,0.84,0.0,1.48,1.48,0.17,1.48,0.19,1.48]}'

# 位置+电流混合控制 (所有关节200mA限流)
curl -X POST http://192.168.1.100:8088/api/set_pvc \
  -H 'Content-Type: application/json' \
  -d '{"position_rad":[0.5,-0.8,0.4,0,1.0,1.0,0.1,1.0,0.1,1.0],"torque":[200,200,200,200,200,200,200,200,200,200]}'
```

**返回示例**

```json
{"success": true, "message": "PVC 设置成功"}
```

**混合控制返回**

```json
{"success": true, "message": "混合控制(Pos+Torque)设置成功"}
```

---

### 4.8 POST /api/set_motor — 电机位置控制

直接设置原始电机编码器位置（0–4096）。

| 项 | 值 |
|---|---|
| 请求方式 | `POST` |
| 接口地址 | `/api/set_motor` |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| motor | int[10] | **是** | 目标电机位置，每个值 [0, 4096] |

**返回参数**

| 字段 | 类型 | 说明 |
|---|---|---|
| success | bool | |
| message | string | |
| target | int[10] | 目标值 |
| actual | int[10] | 设备返回的实际位置 |

```bash
# 设置到安全中间位置（demo 中验证过的安全值）
curl -X POST http://192.168.1.100:8088/api/set_motor \
  -H 'Content-Type: application/json' \
  -d '{"motor":[2048,2048,4096,2048,4096,4096,2048,4096,2048,4096]}'
```

> **警告**：由于手指机械限位，部分电机无法达到极限值（0 或 4096）。使用极限值可能导致电机堵转。推荐使用归一化 `/api/set_pos` 接口。

---

### 4.9 GET / — 网页控制面板

浏览器直接打开，提供 10 关节独立滑块控制、快捷操作按钮、实时状态显示和错误监控。

```
http://<主机IP>:8088/
```

---

## 5. WebSocket 接口详解

### 5.1 连接与生命周期

```
connect ws://<主机IP>:8088/ws
  │  连接即开始接收 50ms 周期 status 帧（无需订阅）
  ├─ send {"type":..., "data":{...}}   ← 随时发指令
  ├─ recv {"type":"status"|"result"|"error", ...}
  └─ close / 断线 → 客户端自行重连
```

- 状态帧对**所有连接广播**
- 指令回复仅发给发起连接
- 断线重连：建议 3 秒退避

### 5.2 指令消息总表

统一包装：`{"type":"<类型>","data":{...}}`

| type | data 参数 | 等价 REST | 说明 |
|---|---|---|---|
| `set_pos` | `{"position": [0-1]*10}` | POST /api/set_pos | 归一化位置 |
| `set_pvc` | `{"position_rad": [...], "torque": [...]}` | POST /api/set_pvc | 弧度控制 |
| `set_motor` | `{"motor": [0-4096]*10}` | POST /api/set_motor | 电机位置控制 |
| `status` | `{}` | GET /api/status | 查询状态 |
| `pose` | `{}` | GET /api/pose | 查询位置 |
| `pvc` | `{}` | GET /api/pvc | 查询 PVC |
| `config` | `{}` | GET /api/config | 查询配置 |
| `errors` | `{}` | GET /api/errors | 查询错误码 |

### 5.3 推送帧结构

**StatusFrame（50ms 周期，自动推送）**

```json
{
  "type": "status",
  "data": {
    "connected": true,
    "hand_type": "left",
    "name": "omnihand_o10",
    "model": "OmniHand 2025",
    "sn": "O10XXXXXXXXXX",
    "hardware_ver": "1.0.0",
    "software_ver": "1.2.0",
    "dof": 10,
    "timestamp": 1784697264.38,
    "position": [0.50, 0.48, 0.95, 0.10, 0.85, 0.85, 0.05, 0.85, 0.05, 0.85],
    "joint_rad": [0.545, -0.828, 0.798, -0.144, 1.258, 1.258, 0.008, 1.258, 0.010, 1.258],
    "motor_position": [2000, 2100, 3800, 500, 3500, 3500, 200, 3500, 150, 3500],
    "velocity": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "current": [120, 80, 150, 90, 200, 200, 70, 200, 60, 200],
    "error_codes": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "joint_names": ["thumb_roll", "thumb_abad", "thumb_mcp", "index_abad", "index_pip", "middle_pip", "ring_abad", "ring_pip", "pinky_abad", "pinky_pip"],
    "joint_names_cn": ["拇指旋转", "拇指外展", "拇指弯曲", "食指侧摆", "食指弯曲", "中指弯曲", "无名指侧摆", "无名指弯曲", "小指侧摆", "小指弯曲"]
  }
}
```

**ResultFrame（指令回复）**

```json
{"type": "result", "data": {"success": true, "message": "位置设置成功"}}
```

**ErrorFrame（错误）**

```json
{"type": "error", "data": {"message": "未知指令类型: xxx"}}
```

### 5.4 完整交互示例

```
客户端                                      服务器
  │                                              │
  │  ← {"type":"status", ...}  (自动推送开始)    │
  │  ← {"type":"status", ...}                    │
  │                                              │
  │  → {"type":"set_pos","data":{"position":[1,1,1,1,1,1,1,1,1,1]}}
  │  ← {"type":"result","data":{"success":true,"message":"位置设置成功"}}
  │                                              │
  │  ← {"type":"status","data":{"position":[1,1,1,1,1,1,1,1,1,1]}}  (位置已更新)
```

---

## 6. 客户端参考实现

### 6.1 Python 同步 REST 客户端

```python
"""o10_rest_client.py — O10 REST 客户端"""
import requests

class O10Client:
    def __init__(self, host="192.168.1.100", port=8088):
        self.base = f"http://{host}:{port}"

    def _get(self, path, timeout=5):
        return requests.get(self.base + path, timeout=timeout).json()

    def _post(self, path, body, timeout=10):
        r = requests.post(self.base + path, json=body, timeout=timeout)
        j = r.json()
        if not j.get("success"):
            raise RuntimeError(j.get("message", str(j)))
        return j

    # 查询
    def status(self):   return self._get("/api/status")
    def pose(self):     return self._get("/api/pose")
    def pvc(self):      return self._get("/api/pvc")
    def config(self):   return self._get("/api/config")
    def errors(self):   return self._get("/api/errors")

    # 控制
    def set_pos(self, pos):
        return self._post("/api/set_pos", {"position": pos})

    def set_pvc(self, pos_rad, torque=None):
        body = {"position_rad": pos_rad}
        if torque:
            body["torque"] = torque
        return self._post("/api/set_pvc", body)

    def set_motor(self, motor):
        return self._post("/api/set_motor", {"motor": motor})

    # 快捷操作
    def open_hand(self):
        return self.set_pos([1] * 10)

    def close_hand(self):
        return self.set_pos([0] * 10)

    def half_open(self):
        return self.set_pos([0.5] * 10)


if __name__ == "__main__":
    h = O10Client("192.168.1.100")
    print(h.status())
    h.open_hand()
    print(h.pose())
```

### 6.2 Python 异步 WebSocket 客户端

```python
import asyncio, json
import websockets

async def control_hand(host="192.168.1.100", port=8088):
    async with websockets.connect(f"ws://{host}:{port}/ws") as ws:
        # 发送指令
        await ws.send(json.dumps({
            "type": "set_pos",
            "data": {"position": [0.5] * 10}
        }))

        # 接收回复
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "result":
                print(f"结果: {msg['data']}")
                break
            elif msg["type"] == "status":
                print(f"位置: {msg['data']['position']}")

asyncio.run(control_hand())
```

### 6.3 curl 全接口合集

```bash
B=http://192.168.1.100:8088

# 查询
curl $B/api/status
curl $B/api/pose
curl $B/api/pvc
curl $B/api/config
curl $B/api/errors

# 控制
curl -X POST $B/api/set_pos -H 'Content-Type: application/json' \
  -d '{"position":[1,1,1,1,1,1,1,1,1,1]}'          # 张手
curl -X POST $B/api/set_pos -H 'Content-Type: application/json' \
  -d '{"position":[0,0,0,0,0,0,0,0,0,0]}'          # 握拳
curl -X POST $B/api/set_pvc -H 'Content-Type: application/json' \
  -d '{"position_rad":[0.5,-0.8,0.4,0,1.0,1.0,0.1,1.0,0.1,1.0]}'  # 弧度控制
curl -X POST $B/api/set_motor -H 'Content-Type: application/json' \
  -d '{"motor":[2048,2048,4096,2048,4096,4096,2048,4096,2048,4096]}'  # 电机位置
```

---

## 7. 接口支持列表

| 接口 | REST | WebSocket | O10 适配说明 |
|---|---|---|---|
| 完整状态 | GET /api/status | status | 10DOF + 电机位置(0-4096) + 5bit 错误码 |
| 归一化位置查询 | GET /api/pose | pose | 10 自由度 |
| PVC 查询 | GET /api/pvc | pvc | 弧度/速度/电流 |
| 设备配置 | GET /api/config | config | 型号/SN/固件版本 |
| 错误码 | GET /api/errors | errors | 含中文错误详情 |
| 归一化位置控制 | POST /api/set_pos | set_pos | 10 值 [0-1] |
| 弧度控制 | POST /api/set_pvc | set_pvc | 10 值 rad + 可选电流混合控制 |
| 电机位置控制 | POST /api/set_motor | set_motor | 10 值 [0-4096] |
| 控制面板 | GET / | — | 10 关节滑块 |
| 实时推送 | — | status (auto) | 50ms 周期 |

---

## 8. 安全建议

1. **无鉴权设计** — 仅部署于受信隔离网段；对外暴露必须加反向代理（Nginx + BasicAuth / Token）和防火墙白名单
2. `set_pos` 和 `set_pvc` 可能导致手指运动，确保操作区域安全
3. `set_motor` 使用极限值（0 或 4096）可能导致电机堵转，建议优先使用归一化 `set_pos` 接口
4. 不要在多客户端同时发送控制指令——服务器不做业务层互斥
5. 服务器运行在 Linux 上，ZLG CANFD 推荐模式免 root，SocketCAN 需 root 权限

---

*文档结束。接口行为以 `o10_server.py` 源码为最终依据。*
