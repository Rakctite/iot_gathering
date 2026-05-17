from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any


class AsyncLogWorker(threading.Thread):
    def __init__(
        self,
        display_queue: Queue[str],
        debug_enabled: bool = False,
    ) -> None:
        super().__init__(daemon=True)
        self.input_queue: Queue[dict[str, Any]] = Queue()
        self.display_queue = display_queue
        self.debug_enabled = debug_enabled
        self._stop_event = threading.Event()

    def set_debug_enabled(self, enabled: bool) -> None:
        self.debug_enabled = enabled

    def log(self, level: str, source: str, message: str, data: dict[str, Any] | None = None) -> None:
        self.input_queue.put(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": level.upper(),
                "source": source,
                "message": message,
                "data": data or {},
            }
        )

    def stop(self) -> None:
        self._stop_event.set()

    def drain_once(self, timeout: float = 0) -> bool:
        try:
            record = self.input_queue.get(timeout=timeout)
        except Empty:
            return False
        if record["level"] == "DEBUG" and not self.debug_enabled:
            return True
        self.display_queue.put(_format_record(record))
        return True

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.drain_once(timeout=0.2)


def _format_record(record: dict[str, Any]) -> str:
    data = json.dumps(record["data"], ensure_ascii=False, sort_keys=True)
    return f'{record["timestamp"]} [{record["level"]}] {record["source"]}: {record["message"]} {data}'
