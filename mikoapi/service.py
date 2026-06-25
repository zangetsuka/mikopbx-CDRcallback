from __future__ import annotations

import logging
import threading
from typing import Any

from .callback import CallbackWorker
from .collector import CallCollector
from .config import AppConfig
from .database import Database
from .pbx import MikoPBXClient


class CollectorWorker:
    def __init__(self, collector: CallCollector, config: AppConfig):
        self.collector = collector
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._warned_unconfigured = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="collector-worker",
            daemon=True,
        )
        self._thread.start()
        self.logger.info("Collector worker started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.logger.info("Collector worker stopped")

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.collector.enabled,
            "alive": bool(self._thread and self._thread.is_alive()),
            "configured": self.collector.is_configured,
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self.config.collector.enabled:
                    self._stop_event.wait(self.config.collector.interval_seconds)
                    continue

                if not self.collector.is_configured:
                    if not self._warned_unconfigured:
                        self.logger.warning(
                            "Collector is enabled but MikoPBX API credentials are not configured"
                        )
                        self._warned_unconfigured = True
                    self._stop_event.wait(self.config.collector.interval_seconds)
                    continue

                self._warned_unconfigured = False
                self.collector.collect_calls(limit=self.config.collector.batch_limit)
            except Exception:
                self.logger.exception("Unhandled error in collector loop")

            self._stop_event.wait(self.config.collector.interval_seconds)


class ServiceContainer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db = Database(config.db_path)
        self.pbx_client = MikoPBXClient(config.pbx)
        self.collector = CallCollector(self.db, self.pbx_client)
        self.collector_worker = CollectorWorker(self.collector, config)
        self.callback_worker = CallbackWorker(self.db, config)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._started = False

    def start_background_workers(self) -> None:
        if self._started:
            return
        self.collector_worker.start()
        self.callback_worker.start()
        self._started = True
        self.logger.info("Background workers started")

    def stop_background_workers(self) -> None:
        if not self._started:
            return
        self.collector_worker.stop()
        self.callback_worker.stop()
        self._started = False
        self.logger.info("Background workers stopped")

    def get_status(self) -> dict[str, Any]:
        return {
            "collector": self.collector_worker.get_status(),
            "callback": self.callback_worker.get_status(),
            "database": {
                "path": str(self.config.db_path),
                "total_calls": self.db.get_total_count(),
            },
        }
