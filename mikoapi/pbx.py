from __future__ import annotations

import json
import logging
from typing import Any

import requests
import urllib3

from .config import CALL_TYPES, PBXConfig

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class MikoPBXClient:
    """HTTP client for MikoPBX CDR API."""

    def __init__(self, config: PBXConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session = requests.Session()

        if self.config.api_key:
            self.session.headers.update(
                {
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                }
            )

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    def get_calls(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.is_configured:
            self.logger.debug("MikoPBX API is not configured; skipping collection")
            return []

        url = f"{self.config.api_url.rstrip('/')}/pbxcore/api/v3/cdr"
        params = {"limit": max(1, min(limit, 100))}

        try:
            response = self.session.get(
                url,
                params=params,
                verify=self.config.verify_ssl,
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            self.logger.error("Failed to fetch CDR records: %s", exc)
            return []

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            self.logger.error("Failed to parse MikoPBX response JSON: %s", exc)
            return []

        if not payload.get("result"):
            message = payload.get("messages", {}).get("error", "Unknown API error")
            self.logger.error("MikoPBX API returned an error: %s", message)
            return []

        records = payload.get("data", {}).get("records", [])
        self.logger.info("Fetched %s calls from MikoPBX", len(records))
        return records

    @staticmethod
    def analyze_call(call: dict[str, Any]) -> dict[str, Any]:
        segments = call.get("records", [])
        voicemail_segments = []
        queue_segments = []
        sip_segments = []

        for segment in segments:
            dst_chan = segment.get("dst_chan", "").lower()
            if "voicemail" in dst_chan:
                voicemail_segments.append(segment)
            elif "queue" in dst_chan:
                queue_segments.append(segment)
            elif "pjsip" in dst_chan or "sip" in dst_chan:
                sip_segments.append(segment)

        return {
            "linkedid": call.get("linkedid"),
            "src_num": call.get("src_num"),
            "dst_num": call.get("dst_num"),
            "did": call.get("did"),
            "disposition": call.get("disposition"),
            "totalDuration": call.get("totalDuration", 0),
            "totalBillsec": call.get("totalBillsec", 0),
            "start": call.get("start"),
            "segments": segments,
            "has_voicemail": bool(voicemail_segments),
            "voicemail_segments": voicemail_segments,
            "queue_count": len(queue_segments),
            "sip_count": len(sip_segments),
            "segment_count": len(segments),
        }

    @classmethod
    def classify_call(cls, call: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        analysis = cls.analyze_call(call)
        disposition = str(call.get("disposition", "")).upper()

        if analysis["has_voicemail"]:
            return CALL_TYPES["VOICEMAIL"], analysis
        if disposition in {"NO ANSWER", "NOANSWER"}:
            return CALL_TYPES["NOANSWER"], analysis
        return None, analysis
