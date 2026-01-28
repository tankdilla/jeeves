import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SERVICE_NAME = os.getenv("SERVICE_NAME", "jeeves")

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "message",
    "asctime",
}

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": _utc_iso(),
            "level": record.levelname,
            "logger": record.name,
            "service": SERVICE_NAME,
            "host": socket.gethostname(),
            "msg": record.getMessage(),
        }

        # Optional common fields
        component = getattr(record, "component", None)
        if component:
            base["component"] = component

        request_id = getattr(record, "request_id", None)
        if request_id:
            base["request_id"] = request_id

        task_id = getattr(record, "task_id", None)
        if task_id:
            base["task_id"] = task_id

        # Put all custom extras under "props" to avoid collisions
        props: Dict[str, Any] = {}
        for k, v in record.__dict__.items():
            if k in _RESERVED or k.startswith("_"):
                continue
            # keep our top-level keys clean
            if k in {"component", "request_id", "task_id"}:
                continue
            props[k] = v

        if props:
            base["props"] = props

        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)

        return json.dumps(base, ensure_ascii=False)

def get_logger(name: str, component: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger(name)

    # Avoid duplicate handlers (important with uvicorn reload and celery forks)
    if logger.handlers:
        return logger

    logger.setLevel(LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    logger.addHandler(handler)
    logger.propagate = False

    # Attach component once using a LoggerAdapter-like pattern (simple)
    if component:
        return logging.LoggerAdapter(logger, {"component": component})  # type: ignore
    return logger
