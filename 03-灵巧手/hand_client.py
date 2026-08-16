"""O10 灵巧手 HTTP 客户端（参考 ``灵巧手_API接口文档.md``）。

* 默认右手 ``hand_type=right``。
* 使用归一化 ``POST /api/set_pos``（10 维 [0,1]），避免极限值堵转。
* 提供 ``errors_watch`` 上下文：后台线程每 200ms 拉一次 ``/api/errors``，任一非 0
  时记录到 ``watcher.first_error`` 并记日志。**注意：异常在后台线程抛出没有意义**
  （会被线程边界吞掉），使用方必须在 with 块内/后自己检查 ``first_error``::

      with hand.errors_watch() as watcher:
          ...
      if watcher.first_error:
          raise HandError(f"灵巧手错误码非 0: {watcher.first_error}")
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import requests

LOG = logging.getLogger(__name__)


class HandError(RuntimeError):
    """灵巧手业务失败（success=false / 错误码非 0）。"""


class HandClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        hand_type: str = "right",
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        if hand_type not in ("right", "left"):
            raise ValueError("hand_type must be right/left")
        self.base = f"http://{host}:{port}"
        self.hand_type = hand_type
        self.timeout = timeout
        self._s = session or requests.Session()

    # ---- 查询 -------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        r = self._s.get(f"{self.base}/api/status", timeout=5)
        r.raise_for_status()
        return r.json()

    def pose(self) -> list[float]:
        r = self._s.get(f"{self.base}/api/pose", timeout=5)
        r.raise_for_status()
        return r.json().get("position", [])

    def errors(self) -> list[int]:
        r = self._s.get(f"{self.base}/api/errors", timeout=5)
        r.raise_for_status()
        return r.json().get("error_codes", [])

    # ---- 控制 -------------------------------------------------------------

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._s.post(f"{self.base}{path}", json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise HandError(f"HTTP {path} 失败: {e}") from e
        try:
            data = r.json()
        except ValueError as e:
            raise HandError(f"无法解析 {path} 响应: {r.text[:200]}") from e
        if not data.get("success", False):
            raise HandError(data.get("message", "未知失败"))
        return data

    def set_pos(self, position: list[float]) -> dict[str, Any]:
        if len(position) != 10:
            raise ValueError("set_pos 需要 10 维归一化数组")
        if any(not (0.0 <= float(x) <= 1.0) for x in position):
            raise ValueError("set_pos 数值必须全部位于 [0, 1]")
        return self._post_json("/api/set_pos", {"position": [float(x) for x in position]})

    def pose_name(self, name: str, table: dict[str, list[float]]) -> dict[str, Any]:
        if name not in table:
            raise ValueError(f"未知姿态 {name!r}; 可用: {list(table)}")
        return self.set_pos(table[name])

    # ---- 后台错误监控 -----------------------------------------------------

    def errors_watch(
        self,
        interval_s: float = 0.2,
        on_error: Callable[[list[int]], None] | None = None,
    ) -> "_ErrorWatcher":
        return _ErrorWatcher(self, interval_s=interval_s, on_error=on_error)


class _ErrorWatcher:
    """上下文管理器：进入时启动后台线程拉取 errors；退出时停止。"""

    def __init__(
        self,
        hand: HandClient,
        interval_s: float = 0.2,
        on_error: Callable[[list[int]], None] | None = None,
    ) -> None:
        self._hand = hand
        self._interval = interval_s
        self._cb = on_error or _log_on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.first_error: list[int] | None = None

    def __enter__(self) -> "_ErrorWatcher":
        self._thread = threading.Thread(target=self._run, name="HandErrorWatcher", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                codes = self._hand.errors()
            except Exception as e:  # noqa: BLE001
                LOG.debug("errors 拉取失败: %s", e)
                self._stop.wait(self._interval)
                continue
            if any(int(c) != 0 for c in codes):
                self.first_error = codes
                try:
                    self._cb(codes)
                except Exception:  # noqa: BLE001
                    pass
                return
            self._stop.wait(self._interval)


def _log_on_error(codes: list[int]) -> None:
    # 后台线程里抛异常到不了主线程（上面的 except 会吞），只记录；
    # 真正的中止靠使用方检查 watcher.first_error。
    LOG.error("灵巧手错误码非 0: %s（调用方应检查 watcher.first_error 并中止任务）", codes)
