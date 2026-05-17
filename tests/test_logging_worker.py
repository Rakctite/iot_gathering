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
