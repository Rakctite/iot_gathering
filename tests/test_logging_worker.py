from queue import Queue

from industrial_gateway.logging_worker import AsyncLogWorker


def test_async_log_worker_formats_messages_without_blocking_producer():
    display = Queue()
    worker = AsyncLogWorker(display_queue=display)

    worker.log("INFO", "button", "Add Device clicked", {"name": "line-1"})
    worker.drain_once()

    line = display.get_nowait()
    assert "[INFO]" in line
    assert "button" in line
    assert "Add Device clicked" in line
    assert '"name": "line-1"' in line


def test_async_log_worker_hides_debug_messages_when_debug_disabled():
    display = Queue()
    worker = AsyncLogWorker(display_queue=display, debug_enabled=False)

    worker.log("DEBUG", "driver", "read values", {"tag": "speed"})
    worker.drain_once()

    assert display.empty()


def test_async_log_worker_can_suppress_runtime_logs_but_keep_errors(tmp_path):
    display = Queue()
    worker = AsyncLogWorker(
        display_queue=display,
        runtime_log_enabled=False,
        log_dir=tmp_path / "runtime",
        error_log_dir=tmp_path / "error",
    )

    worker.input_queue.put(
        {
            "timestamp": "2026-05-19T01:02:03+00:00",
            "level": "INFO",
            "source": "driver",
            "message": "subscription datachange",
            "data": {"device": "rollgap"},
        }
    )
    worker.input_queue.put(
        {
            "timestamp": "2026-05-19T01:02:04+00:00",
            "level": "ERROR",
            "source": "driver",
            "message": "tag read failed",
            "data": {"device": "rollgap", "error": "missing"},
        }
    )

    worker.drain_once()
    worker.drain_once()

    line = display.get_nowait()
    assert "tag read failed" in line
    runtime_path = tmp_path / "runtime" / "industrial_gateway_2026-05-19.log"
    error_path = tmp_path / "error" / "industrial_gateway_error_2026-05-19.log"
    assert "subscription datachange" not in runtime_path.read_text(encoding="utf-8")
    assert "tag read failed" in runtime_path.read_text(encoding="utf-8")
    assert "tag read failed" in error_path.read_text(encoding="utf-8")


def test_async_log_worker_formats_records_without_timestamp():
    display = Queue()
    worker = AsyncLogWorker(display_queue=display)

    worker.input_queue.put({"level": "INFO", "source": "driver", "message": "read values", "data": {"tag": "speed"}})
    worker.drain_once()

    line = display.get_nowait()
    assert "[INFO]" in line
    assert "driver" in line
    assert "read values" in line
    assert '"tag": "speed"' in line


def test_async_log_worker_formats_driver_and_plugin_context():
    display = Queue()
    worker = AsyncLogWorker(display_queue=display)

    worker.input_queue.put(
        {"level": "ERROR", "source": "driver", "message": "read failed", "data": {"driver": "opcua"}}
    )
    worker.input_queue.put(
        {"level": "ERROR", "source": "plugin", "message": "start failed", "data": {"plugin": "mqtt"}}
    )

    worker.drain_once()
    worker.drain_once()

    assert "[driver][opcua] read failed" in display.get_nowait()
    assert "[plugin][mqtt] start failed" in display.get_nowait()


def test_async_log_worker_writes_daily_log_file(tmp_path):
    display = Queue()
    worker = AsyncLogWorker(display_queue=display, log_dir=tmp_path)

    worker.input_queue.put(
        {
            "timestamp": "2026-05-19T01:02:03+00:00",
            "level": "INFO",
            "source": "driver",
            "message": "started",
            "data": {"device": "opc"},
        }
    )
    worker.drain_once()

    path = tmp_path / "industrial_gateway_2026-05-19.log"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "started" in text
    assert '"device": "opc"' in text


def test_async_log_worker_writes_error_logs_to_separate_directory(tmp_path):
    display = Queue()
    worker = AsyncLogWorker(
        display_queue=display,
        log_dir=tmp_path / "runtime",
        error_log_dir=tmp_path / "error",
    )

    worker.input_queue.put(
        {
            "timestamp": "2026-05-19T01:02:03+00:00",
            "level": "ERROR",
            "source": "driver",
            "message": "read failed",
            "data": {"device": "opc", "error": "timeout"},
        }
    )
    worker.drain_once()

    runtime_path = tmp_path / "runtime" / "industrial_gateway_2026-05-19.log"
    error_path = tmp_path / "error" / "industrial_gateway_error_2026-05-19.log"
    assert runtime_path.exists()
    assert error_path.exists()
    assert "read failed" in error_path.read_text(encoding="utf-8")


def test_async_log_worker_writes_ui_audit_logs_to_separate_directory(tmp_path):
    display = Queue()
    worker = AsyncLogWorker(
        display_queue=display,
        log_dir=tmp_path / "runtime",
        audit_log_dir=tmp_path / "audit",
    )

    worker.input_queue.put(
        {
            "timestamp": "2026-05-19T01:02:03+00:00",
            "level": "INFO",
            "source": "button",
            "message": "Save Plugin clicked",
            "data": {"sink": {"sink_type": "mqtt"}},
        }
    )
    worker.drain_once()

    runtime_path = tmp_path / "runtime" / "industrial_gateway_2026-05-19.log"
    audit_path = tmp_path / "audit" / "industrial_gateway_audit_2026-05-19.log"
    assert runtime_path.exists()
    assert audit_path.exists()
    assert "Save Plugin clicked" in audit_path.read_text(encoding="utf-8")
