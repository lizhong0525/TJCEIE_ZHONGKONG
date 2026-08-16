"""灵巧手开机自检（对应任务清单第 3 部分）。

用法：
    python hand_bringup.py --host 192.168.1.100

步骤：status → errors → 【0/1 方向验证】（文档自相矛盾，必须真机确认一次）。

方向验证原理：文档 §3.1 说"归一化 0=张开、1=闭合"，§4.6 示例却写
"[1]*10=张手、[0]*10=握拳"。两者必有一错。本脚本先后发全 1 和全 0，
由现场人员用眼睛回答"哪一个是张手"，据此确定 OPEN_VALUE/CLOSE_VALUE，
以后所有手型都按这个结论写。
"""
from __future__ import annotations

import argparse
import sys

from hand_client import HandClient, HandError

STEPS = []


def step(name: str, ok: bool, detail: str = "") -> None:
    STEPS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name} {detail}")
    if not ok:
        print("\n自检终止：上一步未通过。")
        sys.exit(1)


def ask(prompt: str) -> str:
    return input(prompt).strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser(description="O10 灵巧手开机自检")
    ap.add_argument("--host", required=True, help="灵巧手服务 IP")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--hand-type", choices=["right", "left"], default="right")
    args = ap.parse_args()

    hand = HandClient(host=args.host, port=args.port, hand_type=args.hand_type)

    # 1. status
    try:
        st = hand.status()
        ok = bool(st.get("connected"))
        step("GET /api/status", ok,
             f"connected={st.get('connected')} hand_type={st.get('hand_type')} model={st.get('model')}")
        if st.get("hand_type") != args.hand_type:
            step("手型一致", False, f"配置={args.hand_type} 实际={st.get('hand_type')}")
    except Exception as e:
        step("GET /api/status", False, str(e))

    # 2. errors 全 0
    try:
        codes = hand.errors()
        step("GET /api/errors", all(int(c) == 0 for c in codes), f"error_codes={codes}")
    except Exception as e:
        step("GET /api/errors", False, str(e))

    # 3. 0/1 方向验证（需要人眼）
    print("\n=== 方向验证（文档自相矛盾，必须确认一次）===")
    print("即将发送 set_pos([1]*10)。请观察手指动作，注意安全。")
    if ask("准备好了？(y/n) ") != "y":
        print("已取消。")
        return 2
    try:
        hand.set_pos([1.0] * 10)
    except HandError as e:
        step("set_pos([1]*10)", False, str(e))
    ans1 = ask("刚才的动作是【张手】吗？(y/n) ")
    try:
        hand.set_pos([0.0] * 10)
    except HandError as e:
        step("set_pos([0]*10)", False, str(e))
    ans2 = ask("刚才的动作是【握拳/闭合】吗？(y/n) ")

    if ans1 == "y" and ans2 == "y":
        open_v, close_v = 1, 0
        step("方向验证", True, "结论：1=张手（与文档 §4.6 示例一致）")
    elif ans1 == "n" and ans2 == "n":
        open_v, close_v = 0, 1
        step("方向验证", True, "结论：0=张手（与文档 §3.1 数据字典一致）")
    else:
        step("方向验证", False, f"回答矛盾（全1是张手?{ans1} / 全0是握拳?{ans2}），请检查设备后重跑")

    print(f"\n结论：OPEN_VALUE={open_v}  CLOSE_VALUE={close_v}")
    print("请把该结论写进 01-算法服务/config/site.yaml 的 hand.poses（手型唯一来源，")
    print("本目录不再另存副本），并据此标定 grasp_digit / grasp_shape / tap 等手型。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
