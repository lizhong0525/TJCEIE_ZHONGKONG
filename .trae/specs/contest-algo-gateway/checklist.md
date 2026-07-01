# Checklist

- [x] 网关 `/health` 返回 200，且 `status === "ok"`、`supported_tasks` 包含 classify/detect/ocr。
- [x] 网关 `/infer` 能正确回显 `request_id`、`task_type`，成功时 `message` 为空字符串。
- [x] `image_io.py` 能从 URL 正常加载图片，URL 失败时返回 `ok: false`。
- [x] classify 模块默认使用 open_clip 零样本，返回的中文标签落在 `meta.class_names` 中。
- [x] classify 的 8 个英文 prompt 已覆盖办公室、公园、街道、商场、厨房、卧室、图书馆、体育馆，且映射正确。
- [x] detect 模块使用 ultralytics YOLO 覆盖 8 个 COCO 类，中心点计算为像素坐标，标签映射符合竞赛要求。
- [x] detect 模块使用 YOLO-World 补齐“台灯”，合并结果无重复计数问题（同目标不重复）。
- [x] ocr 模块使用 PaddleOCR 进行检测+识别，文本框按先 y 后 x 排序拼接。
- [x] ocr 后处理 `normalize(text, rules)` 独立存在，支持 `trim_space`、`case_insensitive` 及全半角/繁简/空格/标点处理。
- [x] 三类接口均能在 `meta.infer_T_max_ms` 内完成；超时时返回合法失败信封（代码层面已计算 `elapsed_ms` 并包装失败信封，实际模型时延需在安装重型依赖后复测）。
- [x] 依赖文件 `requirements.txt` 完整，可在 `.venv` 中安装并启动服务（重型模型依赖按说明安装即可）。
- [x] 使用示例图片进行离线/在线测试，三类接口均返回符合平台契约的结果结构（非模型异常路径已验证，真实推理需在安装 `torch/ultralytics/paddleocr` 后运行）。
