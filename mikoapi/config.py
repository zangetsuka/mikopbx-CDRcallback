from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

CALL_TYPES = {
    "NOANSWER": "no_answer",
    "VOICEMAIL": "voicemail",
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _resolve_path(name: str, default: str) -> Path:
    raw = _env_str(name, default)
    path = Path(raw)
    if path.is_absolute():
        return path
    return BASE_DIR / path


@dataclass(slots=True)
class PBXConfig:
    api_url: str
    api_key: str
    verify_ssl: bool
    request_timeout: int

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url and self.api_key)


@dataclass(slots=True)
class WebConfig:
    host: str
    port: int
    debug: bool


@dataclass(slots=True)
class CollectorConfig:
    enabled: bool
    interval_seconds: int
    batch_limit: int


@dataclass(slots=True)
class CallbackConfig:
    enabled: bool
    auto_create: bool
    delay_minutes: int
    max_delay_minutes: int
    notification_audio: str
    notification_retries: int
    min_operators: int
    max_wait_time: int
    scheduler_interval_seconds: int
    retry_delay_seconds: int
    max_retries: int
    dry_run: bool
    operator_extension: str
    ami_host: str
    ami_port: int
    ami_username: str
    ami_password: str
    callback_queue: str
    callback_queue_context: str
    callback_context: str
    originate_timeout: int
    operator_ring_seconds: int

    def settings_defaults(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "routing_mode": "queue",
            "caller_id": "",
            "operator_extension": self.operator_extension,
            "client_channel_template": "Local/{phone}@from-internal",
            "delay_no_answer_minutes": self.delay_minutes,
            "delay_voicemail_minutes": self.delay_minutes,
            "operator_ring_seconds": self.operator_ring_seconds,
            "originate_timeout": self.originate_timeout,
            "max_retries": self.max_retries,
            "retry_delay_minutes": max(1, int(self.retry_delay_seconds / 60)),
            "work_hours_enabled": False,
            "work_hours_start": "09:00",
            "work_hours_end": "20:00",
            "work_days": "1,2,3,4,5",
            "work_time_intervals": [
                {
                    "start": "09:00",
                    "end": "20:00",
                    "days": [1, 2, 3, 4, 5],
                }
            ],
            "dedup_window_minutes": 30,
            "delay_minutes": self.delay_minutes,
            "max_delay_minutes": self.max_delay_minutes,
            "notification_audio": self.notification_audio,
            "notification_retries": self.notification_retries,
            "min_operators": self.min_operators,
            "max_wait_time": self.max_wait_time,
            "callback_queue": self.callback_queue,
            "auto_create": self.auto_create,
            "retry_backoff_minutes": "5,15,30",
            "max_concurrent_calls": 0,
            "max_calls_per_minute": 5,
            "check_operator_busy": False,
            "busy_check_extension": "",
            "busy_check_context": "internal",
            "busy_retry_seconds": 60,
            "task_ttl_minutes": 0,
        }

    @property
    def ami_is_configured(self) -> bool:
        return bool(
            self.ami_host
            and self.ami_port
            and self.ami_username
            and self.ami_password
        )


@dataclass(slots=True)
class LoggingConfig:
    level: str
    file_path: Path


@dataclass(slots=True)
class AppConfig:
    base_dir: Path
    db_path: Path
    log_dir: Path
    pbx: PBXConfig
    web: WebConfig
    collector: CollectorConfig
    callback: CallbackConfig
    logging: LoggingConfig
    secret_key: str
    web_auth_enabled: bool
    web_auth_password: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        db_path = _resolve_path("MIKO_DB_PATH", "data/mikoapi.db")
        log_file = _resolve_path("MIKO_LOG_FILE", "logs/mikoapi.log")

        return cls(
            base_dir=BASE_DIR,
            db_path=db_path,
            log_dir=log_file.parent,
            pbx=PBXConfig(
                api_url=_env_str("MIKO_API_URL"),
                api_key=_env_str("MIKO_API_KEY"),
                verify_ssl=_env_bool("MIKO_VERIFY_SSL", False),
                request_timeout=_env_int("MIKO_REQUEST_TIMEOUT", 30),
            ),
            web=WebConfig(
                host=_env_str("MIKO_WEB_HOST", "0.0.0.0"),
                port=_env_int("MIKO_WEB_PORT", 5000),
                debug=_env_bool("MIKO_WEB_DEBUG", False),
            ),
            collector=CollectorConfig(
                enabled=_env_bool("MIKO_COLLECTOR_ENABLED", True),
                interval_seconds=max(5, _env_int("MIKO_COLLECT_INTERVAL", 30)),
                batch_limit=max(1, min(_env_int("MIKO_COLLECT_LIMIT", 50), 100)),
            ),
            callback=CallbackConfig(
                enabled=_env_bool("CALLBACK_ENABLED", True),
                auto_create=_env_bool("CALLBACK_AUTO_CREATE", True),
                delay_minutes=max(0, _env_int("CALLBACK_DELAY_MINUTES", 2)),
                max_delay_minutes=max(1, _env_int("CALLBACK_MAX_DELAY", 5)),
                notification_audio=_env_str(
                    "CALLBACK_NOTIFICATION_AUDIO", "callback-notification"
                ),
                notification_retries=max(
                    0, _env_int("CALLBACK_NOTIFICATION_RETRIES", 3)
                ),
                min_operators=max(1, _env_int("CALLBACK_MIN_OPERATORS", 1)),
                max_wait_time=max(30, _env_int("CALLBACK_MAX_WAIT_TIME", 300)),
                scheduler_interval_seconds=max(
                    5, _env_int("CALLBACK_SCHEDULER_INTERVAL", 10)
                ),
                retry_delay_seconds=max(
                    10, _env_int("CALLBACK_RETRY_DELAY_SECONDS", 120)
                ),
                max_retries=max(1, _env_int("CALLBACK_MAX_RETRIES", 3)),
                dry_run=_env_bool("CALLBACK_DRY_RUN", False),
                operator_extension=_env_str("CALLBACK_OPERATOR_EXTENSION", "200"),
                ami_host=_env_str("AMI_HOST", "127.0.0.1"),
                ami_port=max(1, _env_int("AMI_PORT", 5038)),
                ami_username=_env_str("AMI_USERNAME"),
                ami_password=_env_str("AMI_PASSWORD"),
                callback_queue=_env_str("CALLBACK_QUEUE", "callback_queue"),
                callback_queue_context=_env_str(
                    "CALLBACK_QUEUE_CONTEXT", "from-queue"
                ),
                callback_context=_env_str("CALLBACK_CONTEXT", "from-internal"),
                originate_timeout=max(
                    10, _env_int("CALLBACK_ORIGINATE_TIMEOUT", 60)
                ),
                operator_ring_seconds=max(
                    1, _env_int("CALLBACK_OPERATOR_RING_SECONDS", 2)
                ),
            ),
            logging=LoggingConfig(
                level=_env_str("MIKO_LOG_LEVEL", "INFO").upper(),
                file_path=log_file,
            ),
            secret_key=_env_str("FLASK_SECRET_KEY", "mikoapi-dev-secret"),
            web_auth_enabled=_env_bool("WEB_AUTH_ENABLED", True),
            web_auth_password=_env_str("WEB_AUTH_PASSWORD", "admin"),
        )

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
