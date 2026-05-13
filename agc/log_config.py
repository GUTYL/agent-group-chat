"""AGC 统一日志配置"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

_LOG_FILE: Path | None = None


def get_log_file() -> Path | None:
    return _LOG_FILE


def setup_logging(
    session_type: str,
    session_id: str = "",
    log_dir: str = "data/logs",
    level: str = "INFO",
) -> Path:
    """初始化AGC日志系统。

    - 仅输出到文件（控制台不显示日志）
    - 文件名: {type}_{session_id}.log
    - 抑制 httpx/openai 等第三方库的噪音
    """
    global _LOG_FILE

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    safe_id = session_id.replace("/", "_").replace(" ", "_") if session_id else datetime.now().strftime("%H%M%S")
    log_file = log_path / f"{session_type}_{safe_id}.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    root_logger = logging.getLogger("agc")
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.propagate = False

    if level.upper() == "DEBUG":
        logging.getLogger("httpx").setLevel(logging.DEBUG)
    else:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _LOG_FILE = log_file
    return log_file
