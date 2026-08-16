# 决赛提交参考清单（team01_supcon-cup-2026-final → work）

> 依据：`work/决赛提交对比-0816.md` 的完整对比。
> 原则：**算法/工程/测试以 work 为准；决赛提交只做"参考清单"式移植。**

## 一、✅ 可参考/可移植（work 缺的）

- [ ] **Docker 打包 + 模型预下载**（Dockerfile）
  - CPU torch 走官方 CDN extra-index + 清华 pip 源
  - `HF_ENDPOINT=hf-mirror.com` 国内镜像
  - 构建期预下载 CLIP / Grounding DINO / EasyOCR 模型进镜像
  - `build_image.sh`：构建 → 冒烟验证 → `docker save` 导出 tar（U 盘携带）
- [ ] **现场离线安装方案**
  - `download_wheels.sh`：在家按 `win_amd64/py310` 预下载全部 wheel
  - `现场安装-汪汪队.bat`：离线装依赖 + 拷模型缓存
  - `run_on_site.sh`：Win11 Docker 注意点（`--network host` 不支持 → `host.docker.internal`；USB 受限 → 相机服务跑宿主机）
- [ ] **现场工具三件套**
  - `preheat.py`：模型预热（推理延迟 <3s）
  - `hardware_check.py`：硬件/模型/服务自检汇总（✅/⚠️/❌）
  - `debug_tools.py`：交互控制台（读位姿→直接打印可粘配置格式、Jog、手测试、相机拍照、**模拟竞赛软件调用**）
- [ ] **GET / 根路由**（平台 hermes 轮询 `/`，work 目前只有 /api/health）
- [ ] **README"已知风险与应对"表**格式（坐标未知→标定脚本；模型慢→预热；无外网→镜像打包；SDK 缺失→U 盘携带；API 变更→接口集中）
- [ ] **远程相机服务模式**（`CAMERA_SERVER_URL` + host.docker.internal，Docker 部署时相机 USB 在宿主机）

## 二、❌ 不要搬（决赛提交的坑）

- [ ] apply_calibration.py 的正则注入源码（**正则与实际源码不匹配，必然报错**）
- [ ] mock 测试的"假绿灯"（恒成功 + 亮灯随机返回 + 无失败路径断言）
- [ ] 无并发锁的 FastAPI 端点（并发调用竞态）
- [ ] config.py 硬编码坐标（现场要改代码，不如 site.yaml）
- [ ] task2/task3 的"预设坐标表演"（像素识别不接真实坐标闭环）

## 三、⚠️ 需现场核实的事实冲突

- [ ] 灵巧手硬件型号：决赛版 **DexHand**（:5001，字段 `positions`）vs work **O10**（:8088，字段 `position`）
- [ ] 机械臂/灵巧手实际 IP 与端口
- [ ] 平台是否轮询 `GET /`

## 四、📌 建议执行顺序

1. 核实灵巧手型号/端口（最大事实冲突，决定 01/03 的 hand 模块）
2. 移植 Docker + 离线部署方案（若现场免 Docker 则保留为备选）
3. 补现场工具：预热 / 自检 / 交互调试 + 模拟竞赛调用
4. 补 `GET /` 根路由（确认平台需要后）
5. README 补风险应对表
