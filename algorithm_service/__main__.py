"""``python -m algorithm_service`` 入口。

命令行参数：
  --host    监听地址（默认 0.0.0.0）
  --port    监听端口（默认 5000）
  --config  site.yaml 路径（默认 config/site.yaml）
"""
from __future__ import annotations

import argparse
import logging

from .server import run_app


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    p = argparse.ArgumentParser(description="中控杯复赛选手算法服务")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--config", default="config/site.yaml")
    args = p.parse_args()
    run_app(args.config, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
