import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if hasattr(record, "session_id"):
            log_data["session_id"] = getattr(record, "session_id")
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = getattr(record, "trace_id")
        if hasattr(record, "agent"):
            log_data["agent"] = getattr(record, "agent")
        if hasattr(record, "task_kind"):
            log_data["task_kind"] = getattr(record, "task_kind")
        if hasattr(record, "model"):
            log_data["model"] = getattr(record, "model")
        if hasattr(record, "latency_ms"):
            log_data["latency_ms"] = getattr(record, "latency_ms")
        if hasattr(record, "stage"):
            log_data["stage"] = getattr(record, "stage")
        return json.dumps(log_data)


def configure_json_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
