from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any


class AsyncLogWorker(threading.Thread):
    def __init__(
        self,
        display_queue: Queue[str],
        debug_enabled: bool = False,
        log_dir: str | Path | None = None,
        error_log_dir: str | Path | None = None,
        audit_log_dir: str | Path | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.input_queue: Queue[dict[str, Any]] = Queue()
        self.display_queue = display_queue
        self.debug_enabled = debug_enabled
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self.error_log_dir = Path(error_log_dir) if error_log_dir is not None else None
        self.audit_log_dir = Path(audit_log_dir) if audit_log_dir is not None else None
        self._stop_event = threading.Event()

    def set_debug_enabled(self, enabled: bool) -> None:
        self.debug_enabled = enabled

    def log(self, level: str, source: str, message: str, data: dict[str, Any] | None = None) -> None:
        self.input_queue.put(
            {
                "timestamp": _now_local().isoformat(),
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
        record = _normalize_record(record)
        if record["level"] == "DEBUG" and not self.debug_enabled:
            return True
        line = _format_record(record)
        self.display_queue.put(line)
        self._write_file_log(record, line)
        return True

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.drain_once(timeout=0.2)

    def _write_file_log(self, record: dict[str, Any], line: str) -> None:
        self._write_daily_log(self.log_dir, "industrial_gateway", record, line)
        if _is_error_record(record):
            self._write_daily_log(self.error_log_dir, "industrial_gateway_error", record, line)
        if _is_audit_record(record):
            self._write_daily_log(self.audit_log_dir, "industrial_gateway_audit", record, line)

    def _write_daily_log(self, log_dir: Path | None, prefix: str, record: dict[str, Any], line: str) -> None:
        if log_dir is None:
            return
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"{prefix}_{_log_date(record)}.log"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
        except OSError:
            return


def _format_record(record: dict[str, Any]) -> str:
    data = json.dumps(record["data"], ensure_ascii=False, sort_keys=True)
    return f'{record["timestamp"]} [{record["level"]}] {record["source"]}: {record["message"]} {data}'


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": record.get("timestamp") or _now_local().isoformat(),
        "level": str(record.get("level", "INFO")).upper(),
        "source": record.get("source", "app"),
        "message": record.get("message", ""),
        "data": record.get("data") or {},
    }


def _log_date(record: dict[str, Any]) -> str:
    timestamp = str(record["timestamp"])
    return timestamp[:10]


def _is_error_record(record: dict[str, Any]) -> bool:
    return str(record["level"]).upper() in {"ERROR", "CRITICAL", "EXCEPTION"}


def _is_audit_record(record: dict[str, Any]) -> bool:
    return str(record["source"]).lower() in {"button", "ui", "config", "settings"}


def _now_local() -> datetime:
    return datetime.now().astimezone()
