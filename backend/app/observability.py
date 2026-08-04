from __future__ import annotations

import logging
from contextvars import ContextVar, Token


_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_configured = False
_original_record_factory = logging.getLogRecordFactory()


def configure_logging(level: str = "INFO") -> None:
    """Configure one-line application logs with a request correlation ID."""
    global _configured
    if _configured:
        return

    normalized_level = getattr(logging, level.upper(), logging.INFO)

    def record_factory(*args, **kwargs):
        record = _original_record_factory(*args, **kwargs)
        record.request_id = _request_id.get()
        return record

    logging.setLogRecordFactory(record_factory)
    logging.basicConfig(
        level=normalized_level,
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "request_id=%(request_id)s %(message)s"
        ),
    )
    # 应用自己会记录必要的异常和任务阶段。关闭 Uvicorn 每个请求一行的
    # access log，避免长 URL、CORS OPTIONS 与应用日志重复刷屏。
    logging.getLogger("uvicorn.access").disabled = True
    _configured = True


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str) -> Token[str]:
    return _request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)
