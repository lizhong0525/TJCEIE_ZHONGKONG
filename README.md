# 中控杯决赛 · 赛题 2「工业多模态感知与无人化智能操作」

选手算法服务 + 各模块工作台。比赛（2026-08-18/19，杭州）时竞赛软件只调 4 个 HTTP 接口
（`GET /api/health` + `POST /api/task1|2|3/execute`），只看返回的 `success` 字段；
识别、规划、抓取全部在自家服务里完成。

## 文档导航（全项目就 4 份文档）

| 文件 | 内容 |
|---|---|
| `README.md` | 本页：定位、结构、怎么跑、约定、当前状态 |
| `任务清单.md` | 赛制拆解成可打勾的动作清单（权威进度依据） |
| `操作指南.md` | 本地自检、对接验收、打包部署、相机标定链、现场 11 步、硬件备忘 |
| `遗留问题.md` | 高危风险、赛前待办、各模块"还剩啥"、历史报告归档说明 |

## 目录结构

```text
01-算法服务/        选手算法服务（上场跑的就是它）：aiohttp 4 接口 + site.yaml 配置体系
                    + 动作库 + tools（selftest / calibrate / site_check / debug_console）
02-机械臂/          B9 客户端独立调试副本 + arm_bringup 开机自检 + 离线测试
03-灵巧手/          O10 客户端独立调试副本 + hand_bringup（含 0/1 方向验证）+ 离线测试
04-相机/            Gemini335 采集 / D2C 对齐 / 内参 / 手眼标定 / 台面拟合 + verify_known_point
05-赛题1-按钮开关/   亮灯识别模块副本 + 合成测试（正式服务以 01 为准）
06-赛题2-长方体转运/ 数字识别模块副本（OCR 已对齐 01）+ 合成测试
07-赛题3-几何体分拣/ 形状分类 2D 模块副本 + 合成测试（7.2 四分类 + 7.3 点云位姿已整合进 01）
08-联调测试/        官方 mock 副本（空 body 已对齐真服务）+ 对接验收
09-现场部署/        conda-pack 完整环境（首选）/ wheels（备选）+ 现场安装.bat
```

工作区根（不入库）另有：`grasp_sorting_project/`（赛题 3 形状识别 7.2 的开发主场，
四分类器已移植进 01 的 `tasks/shape_classifier.py`，改算法先在那改、测试绿了再同步）、
官方接口文档、竞赛测试工具、参考仓库副本（team01 / team02 / TJCEIE_ZHONGKONG-main，别改）。

## 怎么跑

```powershell
cd 01-算法服务
python -m tools.service_selftest     # 端到端自检 28 项（改完必须全绿）
python -m algorithm_service          # 起服务 0.0.0.0:5000（读 config/site.yaml）
python -m tools.site_check           # 标定日 30 秒汇总（臂/手/相机/服务/未标定项）
python -m tools.calibrate            # 交互式录入标定值
python -m tools.debug_console        # 读位姿直接打印可粘进 site.yaml 的格式

cd ../02-机械臂 && python test_arm_client_offline.py         # 离线 11 项
cd ../03-灵巧手 && python test_hand_client_offline.py        # 离线 9 项
cd ../04-相机 && python tools/selftest.py                    # 离线 8 项（无相机可跑）
cd ../05-赛题1-按钮开关 && python test_task1_synthetic.py    # 合成 6 项
cd ../06-赛题2-长方体转运 && python test_task2_synthetic.py  # 合成 5 项（要本机 tesseract）
cd ../07-赛题3-几何体分拣 && python test_task3_synthetic.py  # 合成 5 项
```

技术栈：Python 3.11/3.12、aiohttp、OpenCV(**contrib**)、numpy（1.x）、requests、websockets；
OCR 靠 tesseract（≥5 + eng 语言数据）；相机 SDK = pyorbbecsdk2（导入名 pyorbbecsdk）。
**依赖冻结，不许加新包**——现场工控机无外网，部署包按现状打。

## 核心约定（碰代码前背下来）

- **占位符防线**：site.yaml 里 `__现场标定后填入__` 一律抛中文 `PickError` 拒动，绝不静默猜坐标。
- **手眼链唯一约定**：`p_base = t_base_end(拍照时刻) @ t_end_camera(site.yaml hand_eye) @ p_cam`，
  解算只走 `01-算法服务/algorithm_service/tasks/_coords.py`；`Pose` 只有 x/y/z，
  姿态由 `service.default_rpy` 给。
- **失败收尾**：任何 task 失败先撤回 `safe_home` 再返回 `success=false`；
  `/api/disable` 会掉臂，不是普通停止键。
- **无状态**：服务不记上次结果，每次调用重新拍照判断（竞赛软件会连调同一接口）。
- **手型唯一来源** = site.yaml `hand.poses`；代码注释和文档用中文。

## 当前状态（2026-08-17）

- 01 端到端自检 **28 项全绿**；赛题 3 已整合 7.2 形状四分类（triangular_prism /
  hexagonal_prism / rectangular_prism / cylinder）+ 7.3 点云位姿（质心 + PCA，纯 numpy）。
- 真机/真相机全部未接：手眼/内参/槽位/手型标定都是现场活，照 `操作指南.md` 走。
- 已知隐患和赛前待办全在 `遗留问题.md`。最要紧的三件：灵巧手型号现场确认、
  7.2 噪声圆压 0.90 阈值线（现场图像集必测圆柱漏判）、task1 亮灯无并列拒绝。
