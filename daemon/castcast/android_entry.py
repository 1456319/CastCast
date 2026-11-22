# synchronization-map: section=core-service; role=android-entrypoint; boundaries=android-bridge,api-contract,config-state; doc=docs/SYNCHRONIZATION_MAP.md
"""Run CastCast inside the Android foreground service without exiting Python."""

from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .api import ApiServer
from .service import CastService


def run_blocking(media_root: str, work_dir: str, config_dir: str, stop_requested, ready) -> None:
    stop = threading.Event()
    service = CastService({"media_roots": [media_root], "work_dir": work_dir})
    service.audit_log_path = str(Path(config_dir) / "audit.log")
    audit = RotatingFileHandler(service.audit_log_path, maxBytes=512 * 1024,
                                backupCount=1, encoding="utf-8")
    audit.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger = logging.Logger("castcast.android", level=logging.DEBUG)
    logger.addHandler(audit)

    def record(entry: dict) -> None:
        level = {"debug": logging.DEBUG, "warn": logging.WARNING, "warning": logging.WARNING,
                 "error": logging.ERROR}.get(entry["level"], logging.INFO)
        logger.log(level, "%s", entry["message"])

    api = ApiServer(service, on_shutdown=stop.set)
    service.log_buffer.subscribe(record)
    try:
        if not stop_requested.get():
            service.start()
            if not stop_requested.get():
                api.start()
                ready.set(True)
                service.log(f"Embedded control API listening on 127.0.0.1:{api.port}", "debug")
        while not stop_requested.get() and not stop.wait(0.25):
            pass
    finally:
        ready.set(False)
        api.stop()
        service.cancel_prepare()
        service.stop()
        service.log_buffer.unsubscribe(record)
        audit.close()
