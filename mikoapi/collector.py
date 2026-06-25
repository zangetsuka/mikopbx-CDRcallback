from __future__ import annotations

import logging

from .database import Database
from .pbx import MikoPBXClient


class CallCollector:
    """Collects calls from MikoPBX and stores only relevant ones."""

    def __init__(self, db: Database, client: MikoPBXClient):
        self.db = db
        self.client = client
        self.logger = logging.getLogger(self.__class__.__name__)
        self.existing_ids = self.db.get_all_linked_ids()

    @property
    def is_configured(self) -> bool:
        return self.client.is_configured

    def reload_existing_ids(self) -> None:
        self.existing_ids = self.db.get_all_linked_ids()

    def collect_calls(self, limit: int = 50) -> int:
        calls = self.client.get_calls(limit=limit)
        if not calls:
            return 0

        saved_count = 0
        for call in calls:
            linkedid = call.get("linkedid")
            if not linkedid or linkedid in self.existing_ids:
                continue

            call_type, _analysis = self.client.classify_call(call)
            if not call_type:
                continue

            call_id = self.db.save_call(call, call_type)
            if call_id:
                self.existing_ids.add(str(linkedid))
                saved_count += 1

        if saved_count:
            self.logger.info(
                "Collector saved %s new calls; total in DB: %s",
                saved_count,
                self.db.get_total_count(),
            )
        else:
            self.logger.info("Collector found no new relevant calls")
        return saved_count
