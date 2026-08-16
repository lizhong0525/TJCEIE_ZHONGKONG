# work 进度总览（2026-08-16）

按 `任务清单.md` 的部分顺序组织，每个子文件夹一个模块，均可独立打开干活。
素材来源：本仓库旧版代码（算法服务 + 相机模块 + 标定工具）、官方接口示例 mock（副本在 `08-联调测试/`）。
各文件夹内的 README 有用法和审查细节，本页是"做了啥 / 还剩啥"的总账。

```text
TJCEIE_ZHONGKONG/（仓库根）
├── 01-算法服务/        HTTP 服务骨架（4 接口 + 互斥锁 + 兜底）+ site.yaml 配置体系 + 动作库
├── 02-机械臂/          B9 客户端 + 开机自检脚本 + 离线测试
├── 03-灵巧手/          O10 客户端 + 开机自检（含 0/1 方向验证）+ 手型库模板 + 离线测试
├── 04-相机/            Gemini335 采集/标定全家桶 + 新增的独立已知点验证工具
├── 05-赛题1-按钮开关/   亮灯识别模块 + 规则判分动作序列 + 合成测试
├── 06-赛题2-长方体转运/ 数字识别模块 + 规则判分动作序列 + 合成测试
├── 07-赛题3-几何体分拣/ 形状分类模块 + 规则判分动作序列 + 合成测试
├── 08-联调测试/        官方 mock + 对接验收步骤
├── 09-现场部署/        离线 wheel 包 + 现场安装.bat（工控机无外网）
└── 现场调试清单.md      标定日 11 步照做清单（优先级 赛题2 > 赛题1 > 赛题3）
```

---

## 01-算法服务

**做了啥**：完整拷贝仓库的 `algorithm_service/`（aiohttp 服务、`/api/health`+3 个 task 接口、全局互斥锁、异常兜底、site.yaml 占位校验、`pick/place` 动作库）+ `tools/service_selftest.py` + `tools/calibrate.py`。跑通端到端自检（Overall PASS）。
**2026-08-16 修复完成（原 4 个坑全修，仅本副本）**：
- ① **自检假绿灯** → `service_selftest.py` 重写：10 项场景全断言 `success` 真值 + message 内容 + mock 硬件动作链（开关/槽位坐标、手型序列）；失败路径（无灯/空图/未标定）必须明确 `success=false`。
- ② **task3 裸 ValueError** → 新增 `planner.pose_from_vec3()` 和 `tasks/_coords.py`：任何占位坐标抛中文 `PickError` 指明缺哪项；手眼/内参占位时不再静默用单位矩阵解算错坐标；深度图里中心像素无效时跳过该块而不是猜坐标。
- ③ **task1 重写为真实赛制**：`panel.photo_pose + lamps[](roi+switch) + switches[](kind+pos+act_dir+travel+standoff)` 新 schema；`detect_lit_lamp`（ROI 制，颜色比例+亮度兜底，多灯取最高）；真实点按/拨动序列（接近→tap/flick 手型→压入或拨动→撤离→张手→复位）。
- ④ **拨杆内存状态机删除** → 无状态（规则 5.7），方向由 `act_dir` 配置固定；新增 `flick` 手型（site.yaml、poses.yaml、03 同步）。
- 附带：修出被新自检照出的旧 bug（task3 把 `_Shape` dataclass 当 tuple 解包）；`calibrate.py` 面板段同步新 schema（冒烟验证过）；`server.py` 成功 message 带结果摘要（竞赛软件只看 success 不受影响）。
- **第二轮（同日）**：① `errors_watch` 假监控修复（后台线程抛异常被吞 → 改为任务层检查 `first_error`，8.4 真生效）；② 坐标解算不再每块开相机管线（纯数学，不碰 SDK）；③ 7.7 task3 单块失败继续分拣 / 6.7 task2 抓起重试 N 次（`grasp_retries` 可配）；④ task2 重试同帧化、OCR 临时文件入 temp、tesseract 必须带 eng.traineddata（本机 D:\OCR 缺 eng 曾致全灭）。自检扩到 13 项场景全绿。
- **第三轮（同日，外部审查报告 `代码审查-屎山排查.md`）**：A1 task3 全跳过也拒报 success（`if not placed: raise`）；A2 `Vision` 手眼占位不再静默退单位矩阵（`pixel_to_base` 抛错）；A3 `expected_count` 未标定拒动（数量校验不再失效）；A4 重拍报错数字以当选帧为准；B1 裸 `next()`、B2 手型裸 `float()` 修复；planner 消参数遮蔽/删死代码、`safe_home` 入配置、深度取样 5×5 中值。自检 15 项全绿。
- **第四轮（同日，审查复审）**：task2 重拍选帧改"恰好够 expected 优先、其次更接近"（旧规则"取识别多的"会在首帧误检 5 个/重拍正确 4 个时丢掉正确结果）；`safe_home` 半标定不再静默回退内置默认位（只有三轴全占位才回退，部分填写报清缺哪根轴）；`expected_count` 未标定文案去掉写死的块数假设。
- **第五轮（同日晚，`Bug检查报告-0816.md`）**：① BUG-1 06/04 的 OCR 管线读不出 3/4 → 对齐 01（subprocess 直连 tesseract、psm 8、2x 放大 + 阈值预处理、块面中心紧致裁剪），04 副本同步；② BUG-2 06 测试渲染参数坏（scale 8/t20 Hershey 大字不同 tesseract 版本读法不一）→ 改 01 selftest 同款渲染（黑底+白块+黑数字 1.8/5），06 合成 5/5 过；③ BUG-3/BUG-5 经复核第四轮已修，不重复动；④ BUG-4 mock 空 body 400 与真服务不一致 → 08 副本已对齐（空 body 按 `{}` 放行），task3 接口补实跑验证。第四轮的"专项 7 项"已落盘进 selftest（重拍选帧 3 + safe_home 2 + 文案 2），自检现为 22 项全绿。
- **第六轮（同日晚，清"本地能修"存量）**：① B3 手眼链统一——site.yaml `hand_eye` 语义定为 **T_end_camera**（04 结果原样填入），`pixel_to_base`/`pixel_to_base_pose` 改为 `t_base_end @ t_end_camera` 全链，`t_base_end` 由 `capture()` 拍照时刻自动读 `/api/pose`（缺任一环拒算不猜坐标），selftest 3 个像素链场景锁数学；② B5 收尾——`default_rpy` 入 site.yaml（ArmClient 实例默认姿态，02 副本同步）；③ B7——删掉 `01/config/hand/poses.yaml` 与 `03/poses.yaml` 两份死副本，手型唯一来源 = site.yaml；④ B11 打包——server 双重 `load_cfg` 消除、`3.14159`→`math.pi`、04 `t_end_camera` 局部变量改名 `t_end_from_camera`（JSON key 不变）、`check_camera` 的 `args.save` 副作用改局部变量、`solve_hand_eye` 质量门禁接上 rotation spread（≤2°，合成数据验证过：小角度样本求解误差 0.09 会被门禁拦下，大角度样本还原误差 3.8e-10）。自检 25 项全绿。
- **第七轮（同日晚，对照 team01/team02 工程对比的增量）**：① 结构化 JSONL 请求日志——每次任务落一行到 `logs/YYYYMMDD.jsonl`（time/task/path/success/elapsed_ms/result_message），写失败只告警不影响任务；② `GET /api/config/summary` 调试端点——臂/手连接信息 + 内参是否标定 + **未标定清单** + dryRun 回显；③ `service.dry_run` 开关——true 时服务假跑（接口 success 不动硬件），启动大红字警告（team02 忘关 dry_run 的坑）；④ 响应体加 `elapsedMs`；⑤ `GET /` 根路由探活 + health 返回端点表；⑥ 新增 `tools/site_check.py`（臂/手/相机/服务/未标定项 30 秒汇总自检）和 `tools/debug_console.py`（读位姿直接打印可粘进 site.yaml 的格式，Jog/手型/拍照/模拟调接口）；⑦ pytesseract 残留依赖清除（代码早已 subprocess 直连）。自检 28 项全绿。team01 的正则注入标定、欧拉角喂 Rodrigues、无锁端点、预设坐标表演经核对全是坑，一个没搬。
**还剩啥**：`results/*.json → site.yaml` 映射接线（手眼链代码第六轮已统一为 `t_base_end @ t_end_camera`，04 的 `t_end_camera` 原样填进 site.yaml 即可；接线前视觉结果不得用于真机）；task1 两套亮灯检测现场二选一（05 README 有说明）；真机联调。**待核实事实冲突**：灵巧手型号（我方按 O10 :8088/字段 position，team01 按 DexHand :5001/字段 positions——开赛拿官方文档确认，二选一全仓统一）；平台是否轮询 `GET /`（已加根路由，无害）。

## 02-机械臂

**做了啥**：`arm_client.py`（与 01 同源副本）、`arm_bringup.py` 开机自检（status→controllers→motors→enable→pose→plan_only→可选真实微动）、`test_arm_client_offline.py`（stdlib 假 B9 服务）。
**审查结论**：离线测试 11/11 过（使能解析、直线/plan_only、不可达抛 ArmError、OMPL 仅告警、joints 校验）。
**还剩啥**：全部要真机——bringup 实跑、message 文本与文档核对、60s 上限行为、TF 未就绪等待；业务层记得自己查 OMPL（客户端只告警）。

## 03-灵巧手

**做了啥**：`hand_client.py`（同源副本）、`hand_bringup.py`（status→errors→**0/1 方向验证**，文档 §3.1 与 §4.6 矛盾，必须人眼确认一次）、离线测试。手型唯一来源 = 01 的 site.yaml（原 poses.yaml 副本已删）。
**审查结论**：离线测试 9/9 过（set_pos 校验、pose_name、errors_watch 堵转触发）。
**还剩啥**：全部要真机——方向验证、5 个手型（open/close/grasp_digit/grasp_shape/tap）标定、`set_pvc` 限流抓取调参、抓取确认（电流判据）实测。

## 04-相机

**做了啥**：整包拷贝（采集+D2C 对齐+内参导出+手眼标定+台面拟合+三赛题视觉入口+两个 .bat）；**新增 `tools/verify_known_point.py`**（独立已知点外部验收，补上 4.4 缺口——质量门禁只查自洽查不出系统性错误）。
**审查结论**：拷贝后 selftest 8 项离线数学/配置检查 PASS（无相机时手眼/采集项按 SKIP 处理）；亮灯/OCR/形状的合成功能测试在 05/06/07 各自跑（6+5+5 全过）；verify_known_point 编译通过、判定逻辑经合成数据验证。`vision/task2.py` 的 OCR 段已随 BUG-1 对齐 01（requirements 相应去掉 pytesseract）。
**还剩啥**：全部要真机——装 pyorbbecsdk2 插相机、导出内参、采 ≥12 组手眼样本、求解过门禁、verify_known_point 验收、task1 ROI 标定、task2/3 算法迭代（见 06/07）。

## 05-赛题1-按钮开关

**做了啥**：亮灯识别模块副本 + 规则/判分/动作序列 README + 合成测试（三 ROI 选对、全暗拒绝、并列拒绝、未标定拒绝，6/6 过）。
**还剩啥**：现场标定 3 灯 ROI 和双阈值；标定 3 个开关坐标与类型；点按/拨动动作真机调优；~~接入 01（task1.py 重写）~~ 已完成（01 自检含 push/toggle 双路径断言）；现场把 05 和 01 两套亮灯检测二选一统一。

## 06-赛题2-长方体转运

**做了啥**：数字识别模块副本 + 规则/判分/动作序列 README + 合成测试（数字 1–4 全识别对、四块同图检出，5/5 过）。**2026-08-16 晚修复**：OCR 管线对齐 01（此前 pytesseract+psm 10+整块裁剪，外部审查实测读不出 3/4）；测试渲染改 01 同款（旧 scale 8/t20 渲染在不同 tesseract 版本下结论不一）。
**还剩啥**：现场图像集验证 OCR；像素中心接 `pixel_to_base` 出 world 坐标；标定 4 槽位 + 4 落点 + grasp_digit 手型；记录槽内初始姿态（4 分姿态分）；~~接入 01 并修假绿灯~~ 假绿灯已修（01 自检含 task2 空图必失败断言），接入待真机。

## 07-赛题3-几何体分拣

**做了啥**：形状分类模块副本 + 规则/判分/动作序列 README + 合成测试（4 类全对，5/5 过）；把"平躺圆柱 2D 误判"的已知局限固化成了测试。
**还剩啥**：**上 3D 点云分割 + 位姿估计**（2D 分类撑不住随机姿态，是全场最大技术缺口）；抓起后手腕校正动作库；标定 4 槽位 + grasp_shape 手型；~~接入 01 并修裸报错~~ 裸报错已修（占位坐标一律抛中文 PickError），接入待真机。

## 08-联调测试

**做了啥**：官方 mock 拷贝 + 对接验收 7 步 README；mock 实跑验证（health/task1/task2/task3 全 success，空 body 行为已对齐真服务——见 BUG-4 修复）。
**还剩啥**：用 WPF 测试工具实测超时容忍度（--taskX-delay 8/60/120 秒）；真服务替换 mock 后全流程验收。

## 09-现场部署

**做了啥**（第七轮新增）：U 盘清单 + `下载wheels.bat`（pip download 离线包）+ `现场安装.bat`（离线装依赖 → import aiohttp 冒烟 → tesseract eng 数据校验 → 跑 selftest）。依赖轻不做 Docker。
**还剩啥**：在家跑一次 `下载wheels.bat` 生成 wheels/ 目录；确认比赛机 Python 版本（代码要求 3.11/3.12）。

---

## 全局下一步（建议顺序）

1. ~~修 01 的 4 个坑~~ **已完成（2026-08-16）**：假绿灯/裸报错/task1 重写/toggle 无状态真实现；后续四轮审查修复收尾后，01 自检 22 项全绿，02/03/05/06/07 离线回归全过
2. 真机到了：02 bringup → 03 bringup（含方向验证）→ 04 相机链（内参→手眼→门禁→**verify_known_point**）
3. 05/06/07 现场标定 + 算法迭代（07 的 3D 位姿是最大工作量）
4. `results/*.json → site.yaml` 接线 + 交叉校验
5. 08 全流程验收（含超时实测），彩排两遍

**三条红线（全程有效）**：视觉没把握宁可返回失败也别猜坐标去动臂；`/api/disable` 会掉臂，不是普通停止键；物理急停优先于一切软件命令。
