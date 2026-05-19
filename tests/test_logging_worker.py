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
