"""``config/site.yaml`` 加载与占位校验。

设计要点（来自 spec）：

* 所有可现场标定的参数（相机内参/畸变、手眼矩阵、台面尺寸、面板灯/开关坐标、
  数字与形状赛具）都从这里读，代码中不写死任何长度数值。
* 缺失或保留 ``__现场标定后填入__`` 占位时记录 warning，不抛异常。
* 数据类 ``SiteConfig`` 暴露给业务层；含一个 ``is_placeholder`` 工具方法
  方便上层在动作前再次提醒。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

LOG = logging.getLogger(__name__)

PLACEHOLDER = "__现场标定后填入__"


# ---------------------------------------------------------------------------
# dataclass 模型
# ---------------------------------------------------------------------------


@dataclass
class Vec3:
    x: Any = PLACEHOLDER
    y: Any = PLACEHOLDER
    z: Any = PLACEHOLDER

    def as_tuple(self) -> tuple[float, float, float]:
        return (float(self.x), float(self.y), float(self.z))


@dataclass
class CameraIntrinsics:
    fx: Any = PLACEHOLDER
    fy: Any = PLACEHOLDER
    cx: Any = PLACEHOLDER
    cy: Any = PLACEHOLDER


@dataclass
class CameraDistortion:
    k1: float = 0.0
    k2: float = 0.0
    p1: float = 0.0
    p2: float = 0.0


@dataclass
class HandEye:
    """基座→相机的 4×4 变换矩阵。"""

    matrix: list[list[Any]] = field(
        default_factory=lambda: [[PLACEHOLDER] * 4 for _ in range(4)]
    )


@dataclass
class SafeBox:
    """工作域安全区。目标点必须落在 x∈[x_min, x_max]、y/z 同理。"""

    x_min: Any = PLACEHOLDER
    x_max: Any = PLACEHOLDER
    y_min: Any = PLACEHOLDER
    y_max: Any = PLACEHOLDER
    z_min: Any = PLACEHOLDER
    z_max: Any = PLACEHOLDER

    def contains(self, p: Vec3) -> bool:
        try:
            return (
                self.x_min <= float(p.x) <= self.x_max
                and self.y_min <= float(p.y) <= self.y_max
                and self.z_min <= float(p.z) <= self.z_max
            )
        except (TypeError, ValueError):
            return False


@dataclass
class Lamp:
    """面板指示灯（赛题 1：共 3 个，每次随机亮 1 个）。

    ``roi`` 是拍照位下该灯的像素区域 ``[u0, v0, u1, v1]``，现场标定；
    任一元素为负视为未标定。
    ``switch`` 是该灯正下方开关的 ``name``（见 :class:`Switch`）。
    """

    name: str = ""
    color: str = "red"        # red / yellow / green
    roi: list[int] = field(default_factory=list)
    switch: str = ""


@dataclass
class Switch:
    """面板开关（赛题 1：2 个自复位按钮 + 1 个拨动开关）。

    ``kind`` 取值：
      * ``push``   自复位按钮（沿 ``act_dir`` 点按）
      * ``toggle`` 拨动开关（沿 ``act_dir`` 拨动 ``travel`` 米）

    ``act_dir`` 为作用方向单位向量（基座系）：按钮=压入面板方向，拨动=拨杆走向。
    ``travel`` 作用行程（m）；``standoff`` 接近点沿反方向的退让距离（m）。
    """

    name: str = ""
    kind: str = "push"        # push / toggle
    pos: Vec3 = field(default_factory=Vec3)
    act_dir: Vec3 = field(default_factory=Vec3)
    travel: float = 0.005
    standoff: float = 0.06


@dataclass
class Panel:
    photo_pose: Vec3 = field(default_factory=Vec3)  # 拍照位（能看清整个面板的末端位置）
    lamps: list[Lamp] = field(default_factory=list)
    switches: list[Switch] = field(default_factory=list)


@dataclass
class Slot:
    name: str = ""
    pos: Vec3 = field(default_factory=Vec3)


@dataclass
class DigitBlocks:
    """数字长方体赛具配置。"""

    expected_count: int = 0
    placement_order_target: str = "ascending"  # ascending | descending
    grasp_retries: int = 2                     # 单块抓起失败后的重试次数（6.7）
    staging_area: Vec3 = field(default_factory=Vec3)
    placement_area: Vec3 = field(default_factory=Vec3)
    slots: list[Slot] = field(default_factory=list)


@dataclass
class ShapeKind:
    name: str = ""            # triangular_prism / hexagonal_prism / rectangular_prism / cylinder …
    slots: list[Slot] = field(default_factory=list)


@dataclass
class Shapes:
    staging_area: Vec3 = field(default_factory=Vec3)
    kinds: list[ShapeKind] = field(default_factory=list)

    def slots_for(self, name: str) -> list[Slot]:
        for k in self.kinds:
            if k.name == name:
                return k.slots
        return []


@dataclass
class PickPipeline:
    approach_height: Any = PLACEHOLDER  # 抓取前抬升量，单位 m


@dataclass
class HandPoseSet:
    """灵巧手预定义姿态（10 维归一化）。"""

    open: list[float] = field(default_factory=lambda: [1.0] * 10)
    close: list[float] = field(default_factory=lambda: [0.0] * 10)
    grasp_digit: list[float] = field(default_factory=lambda: [0.0] * 10)
    grasp_shape: list[float] = field(default_factory=lambda: [0.0] * 10)
    tap: list[float] = field(default_factory=lambda: [0.0] * 10)
    flick: list[float] = field(default_factory=lambda: [0.0] * 10)


@dataclass
class ServiceConfig:
    arm_host: str = "127.0.0.1"
    arm_port: int = 8087
    arm_side: str = "right"  # 当前默认右臂（Y<0 镜像为 Y>=0 在坐标侧翻转）
    hand_host: str = "127.0.0.1"
    hand_port: int = 8088
    hand_type: str = "right"
    safe_vel: float = 0.12
    final_vel: float = 0.05
    # 安全观察位（任务开始/结束/失败撤回都回这里）；缺省为中置观察位，现场可改
    safe_home: Vec3 = field(default_factory=lambda: Vec3(0.275, 0.0, 0.48))
    # 运动默认末端姿态（已验证推荐姿态，平面向下）；赛题 1 立面面板/赛题 2 姿态分现场可能要调
    default_rpy: tuple[float, float, float] = (-3.141, -1.552, 3.141)
    # JSONL 请求日志目录（相对路径基于 site.yaml 所在项目根解析）
    log_dir: str = "logs"
    # true = 假跑联调模式：接口返回 success 但机器人不动；启动会打大红字警告，上场前必须改回 false
    dry_run: bool = False


@dataclass
class CalibrationConfig:
    """标定流程参数。"""

    cross_check_tol: float = 0.005  # 视觉 vs 人工 交叉校验容差 (m)，现场可调


@dataclass
class SiteConfig:
    service: ServiceConfig = field(default_factory=ServiceConfig)
    camera: CameraIntrinsics = field(default_factory=CameraIntrinsics)
    distortion: CameraDistortion = field(default_factory=CameraDistortion)
    hand_eye: HandEye = field(default_factory=HandEye)
    safe_box: SafeBox = field(default_factory=SafeBox)
    pick: PickPipeline = field(default_factory=PickPipeline)
    hand: HandPoseSet = field(default_factory=HandPoseSet)
    panel: Panel = field(default_factory=Panel)
    digit_blocks: DigitBlocks = field(default_factory=DigitBlocks)
    shapes: Shapes = field(default_factory=Shapes)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# 加载与占位校验
# ---------------------------------------------------------------------------


def _to_float(v: Any, default: Any = PLACEHOLDER) -> Any:
    """YAML 解析时把字符串占位保留为占位；其它能转 float 就转。"""

    if v is None:
        return default
    if isinstance(v, str):
        if v.strip() == PLACEHOLDER or v.strip() == "":
            return default
        try:
            return float(v)
        except ValueError:
            LOG.warning("无法解析数值 '%s'，保留为占位", v)
            return PLACEHOLDER
    try:
        return float(v)
    except (TypeError, ValueError):
        return PLACEHOLDER


def _to_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    if isinstance(v, str):
        if v.strip() == PLACEHOLDER or v.strip() == "":
            return default
        try:
            return int(v)
        except ValueError:
            try:
                return int(float(v))
            except ValueError:
                return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v)


def _to_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _to_pose_list(v: Any, default: list[float]) -> list[float]:
    """手型数组解析：占位/非数值项按 0.0 兜底并告警，绝不让启动崩在裸 float() 上。"""

    if not isinstance(v, list):
        return list(default)
    out: list[float] = []
    for x in v:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            LOG.warning("手型含不可解析项 %r，按 0.0 兜底", x)
            out.append(0.0)
    while len(out) < 10:
        out.append(0.0)
    return out[:10]


def _to_vec3(d: dict[str, Any] | None) -> Vec3:
    d = d or {}
    return Vec3(
        x=_to_float(d.get("x")),
        y=_to_float(d.get("y")),
        z=_to_float(d.get("z")),
    )


def _to_rpy(v: Any) -> tuple[float, float, float]:
    """解析 ``service.default_rpy``；占位/缺项/非数值一律回退已验证推荐姿态。"""

    default = (-3.141, -1.552, 3.141)
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return default
    out: list[float] = []
    for item in v:
        if is_placeholder(item):
            return default
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            return default
    return (out[0], out[1], out[2])


def _to_matrix4(d: dict[str, Any] | None) -> list[list[Any]]:
    d = d or {}
    rows = d.get("rows")
    if isinstance(rows, list) and len(rows) == 4:
        return [[_to_float(c) for c in r] for r in rows]
    # 占位 4×4
    return [[PLACEHOLDER] * 4 for _ in range(4)]


def _to_lamps(items: Iterable[Any]) -> list[Lamp]:
    out: list[Lamp] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        roi_raw = it.get("roi")
        roi = [_to_int(v, -1) for v in roi_raw] if isinstance(roi_raw, list) else []
        out.append(
            Lamp(
                name=_to_str(it.get("name")),
                color=_to_str(it.get("color"), "red"),
                roi=roi,
                switch=_to_str(it.get("switch")),
            )
        )
    return out


def _to_switches(items: Iterable[Any]) -> list[Switch]:
    out: list[Switch] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        kind = _to_str(it.get("kind"), "push")
        default_travel = 0.02 if kind == "toggle" else 0.005
        out.append(
            Switch(
                name=_to_str(it.get("name")),
                kind=kind,
                pos=_to_vec3(it.get("pos")),
                act_dir=_to_vec3(it.get("act_dir")),
                travel=_to_float(it.get("travel"), default_travel),
                standoff=_to_float(it.get("standoff"), 0.06),
            )
        )
    return out


def _to_slots(items: Iterable[Any]) -> list[Slot]:
    return [
        Slot(
            name=_to_str(it.get("name") if isinstance(it, dict) else f"slot{i}"),
            pos=_to_vec3(it.get("pos") if isinstance(it, dict) else None),
        )
        for i, it in enumerate(items or [])
    ]


def _walk_placeholders(node: Any, path: str, missing: list[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_placeholders(v, f"{path}.{k}" if path else k, missing)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_placeholders(v, f"{path}[{i}]", missing)
    elif isinstance(node, str) and node.strip() == PLACEHOLDER:
        missing.append(path)


def collect_placeholders(cfg: SiteConfig) -> list[str]:
    missing: list[str] = []
    _walk_placeholders(cfg.raw, "", missing)
    return missing


def is_placeholder(value: Any) -> bool:
    if isinstance(value, str) and value.strip() == PLACEHOLDER:
        return True
    try:
        return float(value) == float(PLACEHOLDER)
    except (TypeError, ValueError):
        return False


def load(path: str | os.PathLike[str]) -> SiteConfig:
    """加载 ``site.yaml``。文件不存在时返回全占位的默认配置。"""

    p = Path(path)
    if not p.exists():
        LOG.warning("site.yaml 不存在：%s，使用全占位默认", p)
        cfg = SiteConfig()
        return cfg

    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return from_dict(raw)


def from_dict(raw: dict[str, Any]) -> SiteConfig:
    svc_raw = raw.get("service", {}) or {}
    svc = ServiceConfig(
        arm_host=_to_str(svc_raw.get("arm_host"), "127.0.0.1"),
        arm_port=_to_int(svc_raw.get("arm_port"), 8087),
        arm_side=_to_str(svc_raw.get("arm_side"), "right"),
        hand_host=_to_str(svc_raw.get("hand_host"), "127.0.0.1"),
        hand_port=_to_int(svc_raw.get("hand_port"), 8088),
        hand_type=_to_str(svc_raw.get("hand_type"), "right"),
        safe_vel=_to_float(svc_raw.get("safe_vel"), 0.12),
        final_vel=_to_float(svc_raw.get("final_vel"), 0.05),
        safe_home=_to_vec3(svc_raw.get("safe_home")) if svc_raw.get("safe_home") else Vec3(0.275, 0.0, 0.48),
        default_rpy=_to_rpy(svc_raw.get("default_rpy")),
        log_dir=_to_str(svc_raw.get("log_dir"), "logs"),
        dry_run=_to_bool(svc_raw.get("dry_run"), False),
    )

    cam_raw = raw.get("camera", {}) or {}
    cam = CameraIntrinsics(
        fx=_to_float(cam_raw.get("fx")),
        fy=_to_float(cam_raw.get("fy")),
        cx=_to_float(cam_raw.get("cx")),
        cy=_to_float(cam_raw.get("cy")),
    )
    dist_raw = raw.get("distortion", {}) or {}
    dist = CameraDistortion(
        k1=_to_float(dist_raw.get("k1"), 0.0),
        k2=_to_float(dist_raw.get("k2"), 0.0),
        p1=_to_float(dist_raw.get("p1"), 0.0),
        p2=_to_float(dist_raw.get("p2"), 0.0),
    )

    he_raw = raw.get("hand_eye", {}) or {}
    hand_eye = HandEye(matrix=_to_matrix4(he_raw))

    sb_raw = raw.get("safe_box", {}) or {}
    safe_box = SafeBox(
        x_min=_to_float(sb_raw.get("x_min")),
        x_max=_to_float(sb_raw.get("x_max")),
        y_min=_to_float(sb_raw.get("y_min")),
        y_max=_to_float(sb_raw.get("y_max")),
        z_min=_to_float(sb_raw.get("z_min")),
        z_max=_to_float(sb_raw.get("z_max")),
    )

    pick_raw = raw.get("pick", {}) or {}
    pick = PickPipeline(approach_height=_to_float(pick_raw.get("approach_height")))

    hand_raw = raw.get("hand", {}) or {}
    poses_raw = hand_raw.get("poses", {}) or {}
    hand = HandPoseSet(
        open=_to_pose_list(poses_raw.get("open"), [1.0] * 10),
        close=_to_pose_list(poses_raw.get("close"), [0.0] * 10),
        grasp_digit=_to_pose_list(poses_raw.get("grasp_digit"), [0.0] * 10),
        grasp_shape=_to_pose_list(poses_raw.get("grasp_shape"), [0.0] * 10),
        tap=_to_pose_list(poses_raw.get("tap"), [0.0] * 10),
        flick=_to_pose_list(poses_raw.get("flick"), [0.0] * 10),
    )

    panel_raw = raw.get("panel", {}) or {}
    panel = Panel(
        photo_pose=_to_vec3(panel_raw.get("photo_pose")),
        lamps=_to_lamps(panel_raw.get("lamps", [])),
        switches=_to_switches(panel_raw.get("switches", [])),
    )

    db_raw = raw.get("digit_blocks", {}) or {}
    digit_blocks = DigitBlocks(
        expected_count=_to_int(db_raw.get("expected_count"), 0),
        placement_order_target=_to_str(db_raw.get("placement_order_target"), "ascending"),
        grasp_retries=_to_int(db_raw.get("grasp_retries"), 2),
        staging_area=_to_vec3(db_raw.get("staging_area")),
        placement_area=_to_vec3(db_raw.get("placement_area")),
        slots=_to_slots(db_raw.get("slots", [])),
    )

    sh_raw = raw.get("shapes", {}) or {}
    shapes = Shapes(
        staging_area=_to_vec3(sh_raw.get("staging_area")),
        kinds=[
            ShapeKind(
                name=_to_str(k.get("name") if isinstance(k, dict) else ""),
                slots=_to_slots(k.get("slots", []) if isinstance(k, dict) else []),
            )
            for k in (sh_raw.get("kinds") or [])
        ],
    )

    cal_raw = raw.get("calibration", {}) or {}
    calibration = CalibrationConfig(
        cross_check_tol=_to_float(cal_raw.get("cross_check_tol"), 0.005),
    )

    cfg = SiteConfig(
        service=svc,
        camera=cam,
        distortion=dist,
        hand_eye=hand_eye,
        safe_box=safe_box,
        pick=pick,
        hand=hand,
        panel=panel,
        digit_blocks=digit_blocks,
        shapes=shapes,
        calibration=calibration,
        raw=raw,
    )

    missing = collect_placeholders(cfg)
    if missing:
        LOG.warning(
            "site.yaml 含 %d 处占位（__现场标定后填入__），首次启动将不可靠：%s",
            len(missing),
            ", ".join(missing[:6]) + ("…" if len(missing) > 6 else ""),
        )
    return cfg


def write(path: str | os.PathLike[str], raw: dict[str, Any]) -> None:
    """落盘 ``site.yaml``。保留中文字段，UTF-8，禁用别名。"""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
