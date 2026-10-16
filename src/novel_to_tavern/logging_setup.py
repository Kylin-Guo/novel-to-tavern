"""日志配置：所有日志经脱敏过滤器，密钥不可能落盘。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import secrets

LOGGER_NAME = "novel_to_tavern"
DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class RedactionFilter(logging.Filter):
    """把消息与参数里的密钥擦掉。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = secrets.redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: secrets.redact_object(v) for k, v in record.args.items()}
            else:
                record.args = tuple(secrets.redact_object(a) for a in record.args)
        return True


def setup_logging(
    level: str | int = "INFO",
    *,
    log_file: str | Path | None = None,
    stream=None,
) -> logging.Logger:
    """配置根 logger，返回项目 logger。

    重复调用会先清空已有 handler，避免测试间互相污染。
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(DEFAULT_FORMAT)
    redaction = RedactionFilter()

    handlers: list[logging.Handler] = []
    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        handlers.append(file_handler)
    else:
        handlers.append(logging.StreamHandler(stream if stream is not None else sys.stderr))

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(redaction)
        logger.addHandler(handler)

    # 项目 logger 自己输出，不再向根 logger 冒泡，避免重复行。
    logger.propagate = False
    return logger


def get_logger(suffix: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if suffix is None else f"{LOGGER_NAME}.{suffix}")
