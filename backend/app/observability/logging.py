"""TRAFFICINTEL AI - Structured Logging & Request Tracing

Emits one JSON object per log record, carrying the trace id of the request that
produced it. Correlating a rejected signal command with the provider timeout
that preceded it is the difference between a five-minute and a five-hour
incident review.

The trace id travels in a `ContextVar`, so it follows async work without being
threaded through every function signature, and it is returned to the caller in
`X-Request-ID` so an operator reporting a problem can quote it.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
_request_path: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_path", default=None)
_request_method: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_method", default=None)


def current_trace_id() -> Optional[str]:
    return _trace_id.get()


@contextlib.contextmanager
def request_context(trace_id: str, path: str, method: str) -> Iterator[None]:
    """Binds request identity to everything logged inside the block."""
    trace_token = _trace_id.set(trace_id)
    path_token = _request_path.set(path)
    method_token = _request_method.set(method)
    try:
        yield
    finally:
        _trace_id.reset(trace_token)
        _request_path.reset(path_token)
        _request_method.reset(method_token)


class JsonFormatter(logging.Formatter):
    """One JSON object per record, with request context attached."""

    #: Standard LogRecord attributes, excluded so only real extras survive.
    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        trace_id = _trace_id.get()
        if trace_id:
            payload["trace_id"] = trace_id
            payload["path"] = _request_path.get()
            payload["method"] = _request_method.get()

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", structured: bool = True) -> None:
    """Installs the formatter on the root logger. Idempotent."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if structured:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
    root.addHandler(handler)

    # Uvicorn installs its own handlers; route them through ours so a
    # deployment gets one log format rather than two.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
