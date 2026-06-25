"""Callback module - automatic call-back execution for MikoPBX.

Three cooperating pieces:

* SimpleAMIClient - a minimal Asterisk Manager Interface (AMI) client built
  directly on a TCP socket. It exists because MikoPBX advertises a non-standard
  banner ('PBX Call Manager' instead of 'Asterisk Call Manager'), which breaks
  the third-party asterisk-ami library (its listen thread raises and the login
  response is lost). The raw client reads the banner, logs in and sends Originate
  actions, matching replies by ActionID.

* AMIConnector - wrapper that owns a persistent SimpleAMIClient connection and
  exposes originate / originate_to_queue helpers.

* CallbackExecutor - background worker that pulls pending callback tasks from the
  database and places calls using a single-leg originate: dial the CLIENT first,
  then bridge the answered call into the destination queue (queue mode) or operator
  extension (direct mode).

Dialplan note: the client number is dialled through the OUTBOUND context
(e.g. Local/{phone}@outgoing) while the destination queue/operator lives in the
internal context - configured separately.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import threading
import socket
import time
from datetime import datetime
from typing import Any

from .config import AppConfig, CALL_TYPES
from .database import Database


def normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    cleaned = re.sub(r"\D+", "", phone)
    return cleaned


def _parse_call_time(value):
    """Parse a CDR start_time like '2026-06-25 14:01:11.056' into datetime."""
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def _is_client_number(phone, own_dids, pattern=r"[78]\d{10}"):
    """True only for external RU client numbers (7/8 + 10 digits), excluding own DIDs."""
    if not phone or phone in own_dids:
        return False
    return re.fullmatch(pattern, phone) is not None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SimpleAMIClient:
    """Minimal raw-socket Asterisk Manager Interface client.

    The third-party asterisk-ami library cannot parse MikoPBX's custom
    "PBX Call Manager" banner, so we speak AMI directly over a socket.
    """

    def __init__(self, host, port, username, secret, timeout=15):
        self.host = host
        self.port = int(port)
        self.username = username
        self.secret = secret
        self.timeout = timeout
        self.sock = None
        self._buf = b""
        self._counter = 0
        self._lock = threading.Lock()

    def connect(self) -> bool:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._buf = b""
        self._read_line()  # consume banner ("PBX Call Manager")
        resp = self._action({
            "Action": "Login",
            "Username": self.username,
            "Secret": self.secret,
            "Events": "off",
        })
        return str(resp.get("Response", "")).lower() == "success"

    def _read_line(self) -> str:
        while b"\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("AMI connection closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\r\n", 1)
        return line.decode(errors="replace")

    def _read_packet(self) -> dict:
        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("AMI connection closed")
            self._buf += chunk
        raw, self._buf = self._buf.split(b"\r\n\r\n", 1)
        headers = {}
        for ln in raw.decode(errors="replace").split("\r\n"):
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip()] = v.strip()
        return headers

    def _action(self, fields, variables=None, read_timeout=None) -> dict:
        with self._lock:
            self._counter += 1
            action_id = str(self._counter)
            lines = []
            for k, v in fields.items():
                lines.append("%s: %s" % (k, v))
            lines.append("ActionID: %s" % action_id)
            if variables:
                for vk, vv in variables.items():
                    lines.append("Variable: %s=%s" % (vk, vv))
            payload = ("\r\n".join(lines) + "\r\n\r\n").encode()
            self.sock.sendall(payload)
            effective_timeout = read_timeout if read_timeout else self.timeout
            prev_to = None
            if read_timeout and self.sock is not None:
                try:
                    prev_to = self.sock.gettimeout()
                    self.sock.settimeout(effective_timeout)
                except Exception:
                    prev_to = None
            try:
                deadline = time.time() + effective_timeout
                while time.time() < deadline:
                    pkt = self._read_packet()
                    if pkt.get("ActionID") == action_id:
                        return pkt
                return {}
            finally:
                if prev_to is not None and self.sock is not None:
                    try:
                        self.sock.settimeout(prev_to)
                    except Exception:
                        pass

    def extension_state(self, exten, context):
        """Query a dialplan hint via AMI ExtensionState. Returns int status
        (0=idle, 1=inuse, 2=busy, 4=unavailable, 8=ringing, 16=hold,
        -1=no hint) or None on error."""
        try:
            resp = self._action({
                "Action": "ExtensionState",
                "Exten": str(exten),
                "Context": str(context),
            })
        except Exception:
            return None
        if not resp:
            return None
        try:
            return int(resp.get("Status"))
        except (TypeError, ValueError):
            return None

    def originate(self, channel, context, exten, caller_id, timeout, priority=1, variables=None) -> dict:
        fields = {
            "Action": "Originate",
            "Channel": channel,
            "Context": context,
            "Exten": exten,
            "Priority": str(priority),
            "CallerID": caller_id,
            "Timeout": str(int(timeout) * 1000),
            # Synchronous originate: AMI replies "Success" only AFTER the
            # client actually answers and the dialplan (queue/operator) begins
            # to execute -- i.e. the client is really connected to the queue,
            # not merely that the originate request was accepted. A rejected,
            # busy or unanswered call yields "Response: Error".
            "Async": "false",
        }
        # The action response arrives only once call setup concludes, which may
        # take up to the originate timeout, so let the socket wait that long.
        return self._action(fields, variables=variables, read_timeout=int(timeout) + 15)

    def logoff(self) -> None:
        try:
            if self.sock is not None:
                self.sock.sendall(b"Action: Logoff\r\n\r\n")
        except Exception:  # pragma: no cover
            pass
        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:  # pragma: no cover
            pass
        self.sock = None


class AMIConnector:
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.client = None

    def connect(self) -> bool:
        cb = self.config.callback
        try:
            client = SimpleAMIClient(
                cb.ami_host,
                cb.ami_port,
                cb.ami_username,
                cb.ami_password,
                timeout=max(15, cb.originate_timeout),
            )
            if client.connect():
                self.client = client
                self.logger.info("AMI connected to %s:%s", cb.ami_host, cb.ami_port)
                return True
            self.logger.error("AMI login rejected for user %s", cb.ami_username)
            return False
        except Exception as exc:  # pragma: no cover - network dependent
            self.logger.error("AMI connection failed: %s", exc)
            return False

    def extension_state(self, exten, context):
        if self.client is None:
            return None
        try:
            return self.client.extension_state(exten, context)
        except Exception as exc:  # pragma: no cover - network dependent
            self.logger.warning("ExtensionState error: %s", exc)
            return None

    def originate(self, channel, context, extension, caller_id, timeout, variables=None):
        if self.client is None:
            return None
        try:
            resp = self.client.originate(
                channel=channel,
                context=context,
                exten=extension,
                caller_id=caller_id,
                timeout=timeout,
                variables=variables,
            )
        except Exception as exc:  # pragma: no cover - network dependent
            self.logger.error("Originate error: %s", exc)
            return None
        if str(resp.get("Response", "")).lower() == "success":
            return resp.get("ActionID", "ok")
        self.logger.error("Originate rejected: %s", resp)
        return None

    def originate_to_queue(self, phone, queue, caller_id, variables=None):
        return self.originate(
            channel="Local/%s@%s" % (phone, self.config.callback.callback_context),
            context=self.config.callback.callback_context,
            extension=queue,
            caller_id=caller_id,
            timeout=self.config.callback.originate_timeout,
            variables=variables,
        )

    def disconnect(self) -> None:
        if self.client is not None:
            try:
                self.client.logoff()
            except Exception:  # pragma: no cover
                pass
            self.client = None


class CallbackExecutor:
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._connector = None

    def _get_connector(self):
        """Return a live AMI connector, reconnecting if needed (persistent)."""
        connector = self._connector
        if connector is not None and getattr(connector, "client", None) is not None:
            return connector
        connector = AMIConnector(self.config)
        if not connector.connect():
            self._connector = None
            return None
        self._connector = connector
        return connector

    def _reset_connector(self) -> None:
        connector = self._connector
        self._connector = None
        if connector is not None:
            try:
                connector.disconnect()
            except Exception:  # pragma: no cover
                pass

    def execute(self, task: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        """Single-leg callback: originate a call to the client phone and, on
        answer, send the channel to the queue (or operator extension) so the
        agent is connected automatically."""
        phone = str(task["phone"])
        if self.config.callback.dry_run:
            self.logger.info("Dry-run callback task #%s for %s", task["id"], phone)
            return {"success": True, "channel": "dry-run", "duration": 0, "dry_run": True}

        if not self.config.callback.ami_is_configured:
            return {"success": False, "error": "AMI is not configured"}

        routing_mode = str(settings.get("routing_mode", "queue")).strip().lower()
        operator_extension = str(
            task.get("operator_extension")
            or settings.get("operator_extension")
            or self.config.callback.operator_extension
            or ""
        ).strip()
        callback_queue = str(
            settings.get("callback_queue", self.config.callback.callback_queue)
        ).strip()
        originate_timeout = _to_int(
            settings.get("originate_timeout"), self.config.callback.originate_timeout
        )
        channel_template = str(
            settings.get("client_channel_template") or "Local/{phone}@from-internal"
        )

        if routing_mode == "operator":
            target_extension = operator_extension
            if not target_extension:
                return {"success": False, "error": "Operator extension is not configured"}
        else:
            target_extension = callback_queue
            if not target_extension:
                return {"success": False, "error": "Callback queue is not configured"}

        connector = self._get_connector()
        if connector is None:
            return {"success": False, "error": "Failed to connect to AMI"}

        client_channel = channel_template.format(phone=phone)
        try:
            action_id = connector.originate(
                channel=client_channel,
                context=self.config.callback.callback_context,
                extension=str(target_extension),
                caller_id=phone,
                timeout=originate_timeout,
                variables={
                    "CALLBACK_TASK_ID": task["id"],
                    "CALLBACK_PHONE": phone,
                    "CALLBACK_TYPE": task.get("call_type", "manual"),
                    "CALLBACK_AUDIO": settings.get(
                        "notification_audio", self.config.callback.notification_audio
                    ),
                },
            )
            if not action_id:
                self._reset_connector()
                return {"success": False, "error": "Originate failed (no ActionID)"}
            return {
                "success": True,
                "channel": client_channel,
                "target": str(target_extension),
                "routing_mode": routing_mode,
                "duration": 0,
            }
        except Exception as exc:  # pragma: no cover - network dependent
            self._reset_connector()
            return {"success": False, "error": str(exc)}


class CallbackWorker:
    """Creates callback tasks from new calls and executes due tasks."""

    def __init__(self, db: Database, config: AppConfig):
        self.db = db
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._originate_times = []
        self.executor = CallbackExecutor(config)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._warned_disabled = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="callback-worker",
            daemon=True,
        )
        self._thread.start()
        self.logger.info("Callback worker started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.logger.info("Callback worker stopped")

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.callback.enabled,
            "alive": bool(self._thread and self._thread.is_alive()),
            "dry_run": self.config.callback.dry_run,
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self.config.callback.enabled:
                    if not self._warned_disabled:
                        self.logger.info("Callback worker is disabled by configuration")
                        self._warned_disabled = True
                    self._stop_event.wait(self.config.callback.scheduler_interval_seconds)
                    continue

                self._warned_disabled = False
                self._create_automatic_tasks()
                self._process_due_tasks()
            except Exception:
                self.logger.exception("Unhandled error in callback worker loop")

            self._stop_event.wait(self.config.callback.scheduler_interval_seconds)

    def _within_work_hours(self, settings: dict[str, Any]) -> bool:
        if not settings.get("work_hours_enabled", False):
            return True
        now = datetime.now()
        allowed_days = set()
        for part in str(settings.get("work_days", "1,2,3,4,5")).split(","):
            part = part.strip()
            if part.isdigit():
                allowed_days.add(int(part))
        if allowed_days and now.isoweekday() not in allowed_days:
            return False
        try:
            start = datetime.strptime(
                str(settings.get("work_hours_start", "09:00")), "%H:%M"
            ).time()
            end = datetime.strptime(
                str(settings.get("work_hours_end", "20:00")), "%H:%M"
            ).time()
        except ValueError:
            return True
        current = now.time()
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def _effective_settings(self) -> dict[str, Any]:
        return self.db.get_callback_settings(self.config.callback.settings_defaults())

    def _create_automatic_tasks(self) -> None:
        settings = self._effective_settings()
        if not settings.get("enabled", self.config.callback.enabled):
            return
        if not settings.get("auto_create", self.config.callback.auto_create):
            return

        default_delay = _to_int(
            settings.get("delay_minutes"), self.config.callback.delay_minutes
        )
        delay_no_answer = _to_int(settings.get("delay_no_answer_minutes"), default_delay)
        delay_voicemail = _to_int(settings.get("delay_voicemail_minutes"), default_delay)
        dedup_window = _to_int(settings.get("dedup_window_minutes"), 0)
        max_retries = _to_int(
            settings.get("max_retries"), self.config.callback.max_retries
        )

        own_dids = {
            normalize_phone(x)
            for x in str(os.getenv("CALLBACK_OWN_DIDS", "")).split(",")
            if x.strip()
        }
        client_pattern = os.getenv("CALLBACK_CLIENT_NUMBER_REGEX") or r"[78]\d{10}"
        max_call_age = _to_int(os.getenv("CALLBACK_MAX_CALL_AGE_MINUTES"), 60)

        for call in self.db.get_unprocessed_calls():
            phone = normalize_phone(call.get("src_num") or call.get("dst_num"))
            if not phone:
                self.logger.warning(
                    "Skipping callback task for call #%s because no phone was found",
                    call["id"],
                )
                self.db.mark_processed(int(call["id"]))
                continue

            # Only call back real external client numbers (RU 7/8 + 10 digits);
            # never internal extensions, feature codes, or our own DID(s).
            if not _is_client_number(phone, own_dids, client_pattern):
                self.logger.info(
                    "Skipping non-client number %s (call #%s)", phone, call["id"]
                )
                self.db.mark_processed(int(call["id"]))
                continue

            # Skip stale/backlog calls (e.g. CDR history pulled at startup):
            # only call back missed calls newer than CALLBACK_MAX_CALL_AGE_MINUTES.
            if max_call_age > 0:
                call_dt = _parse_call_time(call.get("start_time"))
                if call_dt is not None:
                    age_min = (datetime.now() - call_dt).total_seconds() / 60.0
                    if age_min > max_call_age:
                        self.logger.info(
                            "Skipping old call #%s (age %.1f min > %s min limit)",
                            call["id"], age_min, max_call_age,
                        )
                        self.db.mark_processed(int(call["id"]))
                        continue

            if dedup_window > 0 and self.db.has_recent_callback(phone, dedup_window):
                self.logger.info(
                    "Skipping duplicate callback for %s (within %s min)",
                    phone,
                    dedup_window,
                )
                self.db.mark_processed(int(call["id"]))
                continue

            call_type = str(call.get("call_type") or "manual")
            if call_type == CALL_TYPES["VOICEMAIL"]:
                priority = 8
                delay_minutes = delay_voicemail
            else:
                priority = 5
                delay_minutes = delay_no_answer
            delay_seconds = max(0, delay_minutes) * 60

            task_id = self.db.create_callback_task(
                phone=phone,
                call_type=call_type,
                call_id=int(call["id"]),
                linkedid=call.get("linkedid"),
                delay_seconds=delay_seconds,
                priority=priority,
                source="auto",
                max_retries=max_retries,
            )
            self.db.mark_processed(int(call["id"]))
            self.logger.info(
                "Created callback task #%s for call #%s", task_id, call["id"]
            )

    def _backoff_delay_seconds(self, settings: dict[str, Any], attempt_number: int) -> int:
        """Retry delay (seconds) for this attempt from the backoff schedule
        (e.g. "5,15,30" minutes). Falls back to the fixed delay if unset."""
        raw_value = str(settings.get("retry_backoff_minutes") or "").replace(";", ",")
        steps = []
        for part in raw_value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                steps.append(max(1, int(float(part))))
            except ValueError:
                continue
        if not steps:
            fallback_min = _to_int(settings.get("retry_delay_minutes"), 0)
            if fallback_min > 0:
                return fallback_min * 60
            return self.config.callback.retry_delay_seconds
        idx = min(max(attempt_number - 1, 0), len(steps) - 1)
        return steps[idx] * 60

    def _rate_allows(self, max_per_minute: int) -> bool:
        """True if another originate stays within the per-minute cap."""
        if max_per_minute <= 0:
            return True
        now = time.time()
        self._originate_times = [t for t in self._originate_times if now - t < 60.0]
        return len(self._originate_times) < max_per_minute

    def _record_originate(self) -> None:
        self._originate_times.append(time.time())

    def _operator_available(self, settings: dict[str, Any]):
        """True if operator idle, False if busy/unavailable, None if unknown."""
        exten = str(
            settings.get("busy_check_extension")
            or settings.get("operator_extension")
            or ""
        ).strip()
        if not exten:
            return None
        context = str(
            settings.get("busy_check_context")
            or self.config.callback.callback_context
            or "internal"
        ).strip()
        try:
            connector = self.executor._get_connector()
            status = connector.extension_state(exten, context)
        except Exception as exc:
            self.logger.warning("Operator state check failed (%s); allowing call", exc)
            return None
        if status is None or status < 0:
            return None
        return status == 0

    def _process_due_tasks(self) -> None:
        settings = self._effective_settings()
        if not settings.get("enabled", self.config.callback.enabled):
            return
        if not self._within_work_hours(settings):
            return
        due_tasks = self.db.get_due_callback_tasks(limit=20)
        max_per_cycle = _to_int(settings.get("max_concurrent_calls"), 0)
        max_per_minute = _to_int(settings.get("max_calls_per_minute"), 0)
        check_busy = bool(settings.get("check_operator_busy"))
        started_this_cycle = 0
        for task in due_tasks:
            task_id = int(task["id"])
            attempt_number = int(task.get("retry_count") or 0) + 1
            max_retries = max(
                1,
                _to_int(task.get("max_retries"), self.config.callback.max_retries),
            )
            # Storm protection: cap callbacks launched per dispatch cycle.
            if max_per_cycle > 0 and started_this_cycle >= max_per_cycle:
                self.logger.info(
                    "Per-cycle limit (%s) reached; deferring rest", max_per_cycle
                )
                break
            # Storm protection: cap originate rate per minute.
            if not self._rate_allows(max_per_minute):
                self.logger.info(
                    "Rate limit (%s/min) reached; deferring rest", max_per_minute
                )
                break
            # Operator busy/unavailable -> defer WITHOUT consuming a retry.
            if check_busy and self._operator_available(settings) is False:
                defer = max(5, _to_int(settings.get("busy_retry_seconds"), 60))
                self.db.reschedule_callback_task(task_id, defer)
                self.logger.info(
                    "Operator busy; deferring task #%s by %ss", task_id, defer
                )
                continue
            self._record_originate()
            started_this_cycle += 1
            self.db.start_callback_task(task_id)
            result = self.executor.execute(task, settings)

            if result.get("success"):
                self.db.complete_callback_task(task_id)
                self.db.add_callback_attempt(
                    task_id=task_id,
                    attempt_number=attempt_number,
                    status="completed",
                    channel=result.get("channel"),
                    duration=_to_int(result.get("duration"), 0),
                )
                self.logger.info("Callback task #%s completed", task_id)
                continue

            error_message = str(result.get("error", "Unknown callback execution error"))
            self.db.add_callback_attempt(
                task_id=task_id,
                attempt_number=attempt_number,
                status="failed",
                error_message=error_message,
            )

            if attempt_number < max_retries:
                self.db.retry_callback_task(
                    task_id,
                    error_message,
                    self._backoff_delay_seconds(settings, attempt_number),
                )
                self.logger.warning(
                    "Callback task #%s failed on attempt %s/%s: %s",
                    task_id,
                    attempt_number,
                    max_retries,
                    error_message,
                )
            else:
                self.db.fail_callback_task(task_id, error_message)
                self.logger.error(
                    "Callback task #%s exhausted retries: %s",
                    task_id,
                    error_message,
                )