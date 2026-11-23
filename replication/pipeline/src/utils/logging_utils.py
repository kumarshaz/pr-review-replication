"""Verbose timestamped logging utilities for pr-analysis scripts."""

from __future__ import annotations

import datetime
import logging
import sys
from pathlib import Path

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"


def setup_verbose_logger(
    name: str,
    logs_dir: Path,
    cumulative_filename: str | None = None,
) -> tuple[logging.Logger, Path]:
    """Configure a logger writing to stdout, a timestamped log file, and an optional cumulative log."""
    logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name).strip("_") or "pipeline"
    ts_log_path = logs_path / f"verbose_{safe_name}_{run_ts}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        try:
            existing.close()
        except Exception:
            pass

    formatter = logging.Formatter(LOG_FORMAT)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    ts_handler = logging.FileHandler(ts_log_path, mode="w", encoding="utf-8")
    ts_handler.setLevel(logging.INFO)
    ts_handler.setFormatter(formatter)
    logger.addHandler(ts_handler)

    if cumulative_filename:
        cum_path = logs_path / cumulative_filename
        cum_handler = logging.FileHandler(cum_path, mode="a", encoding="utf-8")
        cum_handler.setLevel(logging.INFO)
        cum_handler.setFormatter(formatter)
        logger.addHandler(cum_handler)

    logger.info("Initialized verbose logger '%s' -> %s", name, ts_log_path)
    return logger, ts_log_path
