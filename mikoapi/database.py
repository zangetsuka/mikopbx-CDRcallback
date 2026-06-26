from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _now_str() -> str:
    return datetime.now().strftime(DATETIME_FORMAT)


class Database:
    """SQLite storage for calls and callback tasks."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.logger = logging.getLogger(self.__class__.__name__)
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init_database(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    linkedid TEXT UNIQUE NOT NULL,
                    src_num TEXT,
                    dst_num TEXT,
                    did TEXT,
                    disposition TEXT,
                    start_time TEXT,
                    total_duration INTEGER DEFAULT 0,
                    total_billsec INTEGER DEFAULT 0,
                    call_type TEXT,
                    has_voicemail INTEGER DEFAULT 0,
                    voicemail_duration INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    processed INTEGER DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id INTEGER NOT NULL,
                    segment_id INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    src_num TEXT,
                    dst_num TEXT,
                    dst_chan TEXT,
                    disposition TEXT,
                    duration INTEGER DEFAULT 0,
                    billsec INTEGER DEFAULT 0,
                    is_voicemail INTEGER DEFAULT 0,
                    FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS callback_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL,
                    call_type TEXT NOT NULL,
                    call_id INTEGER,
                    linkedid TEXT,
                    source TEXT DEFAULT 'manual',
                    status TEXT DEFAULT 'pending',
                    priority INTEGER DEFAULT 5,
                    delay_seconds INTEGER DEFAULT 120,
                    operator_extension TEXT,
                    scheduled_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    last_error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE SET NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS callback_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    channel TEXT,
                    duration INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES callback_tasks(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS callback_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_calls_linkedid ON calls(linkedid)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_calls_start_time ON calls(start_time)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_calls_call_type ON calls(call_type)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_segments_call_id ON segments(call_id)"
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_callback_tasks_status_scheduled
                ON callback_tasks(status, scheduled_at)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_callback_tasks_phone_created
                ON callback_tasks(phone, created_at)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_callback_tasks_call_id
                ON callback_tasks(call_id)
                """
            )

            conn.commit()

        self.logger.info("Database initialized at %s", self.db_path)

    def save_call(self, call_data: dict[str, Any], call_type: str) -> int | None:
        linkedid = call_data.get("linkedid")
        if not linkedid:
            self.logger.warning("Skipped call without linkedid")
            return None

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM calls WHERE linkedid = ?", (linkedid,))
            existing = cursor.fetchone()
            if existing:
                return int(existing["id"])

            has_voicemail = False
            voicemail_duration = 0
            for segment in call_data.get("records", []):
                dst_chan = str(segment.get("dst_chan", "")).lower()
                if "voicemail" in dst_chan:
                    has_voicemail = True
                    voicemail_duration += int(segment.get("duration", 0) or 0)

            cursor.execute(
                """
                INSERT INTO calls (
                    linkedid, src_num, dst_num, did, disposition,
                    start_time, total_duration, total_billsec, call_type,
                    has_voicemail, voicemail_duration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    linkedid,
                    call_data.get("src_num", ""),
                    call_data.get("dst_num", ""),
                    call_data.get("did", ""),
                    call_data.get("disposition", ""),
                    call_data.get("start", ""),
                    int(call_data.get("totalDuration", 0) or 0),
                    int(call_data.get("totalBillsec", 0) or 0),
                    call_type,
                    1 if has_voicemail else 0,
                    voicemail_duration,
                ),
            )
            call_id = int(cursor.lastrowid)

            for segment in call_data.get("records", []):
                dst_chan = str(segment.get("dst_chan", ""))
                cursor.execute(
                    """
                    INSERT INTO segments (
                        call_id, segment_id, start_time, end_time, src_num,
                        dst_num, dst_chan, disposition, duration, billsec,
                        is_voicemail
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        segment.get("id"),
                        segment.get("start"),
                        segment.get("endtime"),
                        segment.get("src_num", ""),
                        segment.get("dst_num", ""),
                        dst_chan,
                        segment.get("disposition", ""),
                        int(segment.get("duration", 0) or 0),
                        int(segment.get("billsec", 0) or 0),
                        1 if "voicemail" in dst_chan.lower() else 0,
                    ),
                )

            conn.commit()

        self.logger.info("Saved call %s as %s", linkedid, call_type)
        return call_id

    def get_calls(
        self,
        call_type: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = [
            """
            SELECT c.*, COUNT(s.id) AS segment_count
            FROM calls c
            LEFT JOIN segments s ON c.id = s.call_id
            """
        ]
        params: list[Any] = []
        filters: list[str] = []

        if call_type:
            filters.append("c.call_type = ?")
            params.append(call_type)

        if search:
            like = f"%{search}%"
            filters.append(
                "(c.src_num LIKE ? OR c.dst_num LIKE ? OR c.linkedid LIKE ?)"
            )
            params.extend([like, like, like])

        if filters:
            query.append("WHERE " + " AND ".join(filters))

        query.append(
            """
            GROUP BY c.id
            ORDER BY c.start_time DESC, c.id DESC
            LIMIT ? OFFSET ?
            """
        )
        params.extend([max(1, limit), max(0, offset)])

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(" ".join(query), params)
            return [dict(row) for row in cursor.fetchall()]

    def get_total_count(
        self, call_type: str | None = None, search: str | None = None
    ) -> int:
        query = ["SELECT COUNT(*) AS total FROM calls"]
        params: list[Any] = []
        filters: list[str] = []

        if call_type:
            filters.append("call_type = ?")
            params.append(call_type)

        if search:
            like = f"%{search}%"
            filters.append("(src_num LIKE ? OR dst_num LIKE ? OR linkedid LIKE ?)")
            params.extend([like, like, like])

        if filters:
            query.append("WHERE " + " AND ".join(filters))

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(" ".join(query), params)
            row = cursor.fetchone()
            return int(row["total"] if row else 0)

    def get_call(self, call_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT c.*, COUNT(s.id) AS segment_count
                FROM calls c
                LEFT JOIN segments s ON c.id = s.call_id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (call_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_call_segments(self, call_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM segments
                WHERE call_id = ?
                ORDER BY segment_id ASC, id ASC
                """,
                (call_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_statistics(self, days: int = 7) -> dict[str, dict[str, Any]]:
        since = (datetime.now() - timedelta(days=max(1, days))).strftime(
            DATETIME_FORMAT
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    call_type,
                    COUNT(*) AS total,
                    SUM(has_voicemail) AS voicemail_count,
                    SUM(total_duration) AS total_duration,
                    AVG(total_duration) AS avg_duration
                FROM calls
                WHERE substr(start_time, 1, 19) >= ?
                GROUP BY call_type
                """,
                (since,),
            )

            stats: dict[str, dict[str, Any]] = {}
            for row in cursor.fetchall():
                stats[row["call_type"]] = {
                    "total": int(row["total"] or 0),
                    "voicemail": int(row["voicemail_count"] or 0),
                    "total_duration": int(row["total_duration"] or 0),
                    "avg_duration": round(float(row["avg_duration"] or 0), 2),
                }

            return stats

    def get_daily_stats(self, days: int = 7) -> list[dict[str, Any]]:
        days = max(1, days)
        first_date = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        rows_by_date: dict[str, dict[str, Any]] = {}

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    substr(start_time, 1, 10) AS call_date,
                    COUNT(*) AS total,
                    SUM(has_voicemail) AS voicemail,
                    SUM(total_duration) AS duration
                FROM calls
                WHERE substr(start_time, 1, 10) >= ?
                GROUP BY substr(start_time, 1, 10)
                ORDER BY call_date ASC
                """,
                (first_date,),
            )
            rows_by_date = {row["call_date"]: dict(row) for row in cursor.fetchall()}

        result = []
        for day_index in range(days):
            date_value = (datetime.now() - timedelta(days=days - day_index - 1)).strftime(
                "%Y-%m-%d"
            )
            row = rows_by_date.get(date_value, {})
            result.append(
                {
                    "date": date_value,
                    "total": int(row.get("total") or 0),
                    "voicemail": int(row.get("voicemail") or 0),
                    "duration": int(row.get("duration") or 0),
                }
            )
        return result

    def get_all_linked_ids(self) -> set[str]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT linkedid FROM calls")
            return {str(row["linkedid"]) for row in cursor.fetchall()}

    def get_unprocessed_calls(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM calls
                WHERE processed = 0
                ORDER BY start_time ASC, id ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def mark_processed(self, call_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE calls SET processed = 1 WHERE id = ?",
                (call_id,),
            )
            conn.commit()

    def create_callback_task(
        self,
        phone: str,
        call_type: str,
        call_id: int | None = None,
        linkedid: str | None = None,
        delay_seconds: int = 120,
        priority: int = 5,
        source: str = "manual",
        operator_extension: str | None = None,
        max_retries: int = 3,
    ) -> int:
        scheduled_at = (
            datetime.now() + timedelta(seconds=max(0, int(delay_seconds)))
        ).strftime(DATETIME_FORMAT)
        created_at = _now_str()

        with self._connect() as conn:
            cursor = conn.cursor()

            if call_id is not None:
                cursor.execute(
                    """
                    SELECT id
                    FROM callback_tasks
                    WHERE call_id = ?
                      AND status IN ('pending', 'in_progress')
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (call_id,),
                )
                existing = cursor.fetchone()
                if existing:
                    return int(existing["id"])

            cursor.execute(
                """
                INSERT INTO callback_tasks (
                    phone, call_type, call_id, linkedid, source, status,
                    priority, delay_seconds, operator_extension, scheduled_at,
                    retry_count, max_retries, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    phone,
                    call_type,
                    call_id,
                    linkedid,
                    source,
                    max(1, min(int(priority), 10)),
                    max(0, int(delay_seconds)),
                    operator_extension,
                    scheduled_at,
                    max(1, int(max_retries)),
                    created_at,
                    created_at,
                ),
            )
            task_id = int(cursor.lastrowid)
            conn.commit()
            return task_id

    def get_callback_tasks(
        self,
        limit: int = 50,
        status: str | None = None,
        phone: str | None = None,
    ) -> list[dict[str, Any]]:
        query = ["SELECT * FROM callback_tasks"]
        params: list[Any] = []
        filters: list[str] = []

        if status:
            filters.append("status = ?")
            params.append(status)

        if phone:
            filters.append("phone LIKE ?")
            params.append(f"%{phone}%")

        if filters:
            query.append("WHERE " + " AND ".join(filters))

        query.append(
            """
            ORDER BY
                CASE status
                    WHEN 'in_progress' THEN 0
                    WHEN 'pending' THEN 1
                    ELSE 2
                END,
                scheduled_at ASC,
                created_at DESC
            LIMIT ?
            """
        )
        params.append(max(1, limit))

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(" ".join(query), params)
            return [dict(row) for row in cursor.fetchall()]

    def get_callback_task(self, task_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM callback_tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_due_callback_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        now_value = _now_str()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM callback_tasks
                WHERE status = 'pending' AND scheduled_at <= ?
                ORDER BY priority DESC, scheduled_at ASC, id ASC
                LIMIT ?
                """,
                (now_value, max(1, limit)),
            )
            return [dict(row) for row in cursor.fetchall()]

    def start_callback_task(self, task_id: int) -> None:
        now_value = _now_str()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE callback_tasks
                SET status = 'in_progress',
                    started_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_value, now_value, task_id),
            )
            conn.commit()

    def complete_callback_task(self, task_id: int) -> None:
        now_value = _now_str()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE callback_tasks
                SET status = 'completed',
                    completed_at = ?,
                    updated_at = ?,
                    last_error = NULL
                WHERE id = ?
                """,
                (now_value, now_value, task_id),
            )
            conn.commit()

    def retry_callback_task(
        self, task_id: int, error_message: str, delay_seconds: int
    ) -> None:
        now_value = _now_str()
        scheduled_at = (
            datetime.now() + timedelta(seconds=max(0, int(delay_seconds)))
        ).strftime(DATETIME_FORMAT)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE callback_tasks
                SET status = 'pending',
                    retry_count = retry_count + 1,
                    last_error = ?,
                    scheduled_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (error_message, scheduled_at, now_value, task_id),
            )
            conn.commit()

    def fail_callback_task(self, task_id: int, error_message: str) -> None:
        now_value = _now_str()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE callback_tasks
                SET status = 'failed',
                    completed_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_value, error_message, now_value, task_id),
            )
            conn.commit()

    def cancel_callback_task(self, task_id: int) -> bool:
        now_value = _now_str()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE callback_tasks
                SET status = 'cancelled',
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('pending', 'in_progress')
                """,
                (now_value, now_value, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def expire_callback_task(self, task_id: int, reason: str = "TTL expired") -> None:
        now_value = _now_str()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE callback_tasks
                SET status = 'expired',
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (reason, now_value, task_id),
            )

    def clear_callback_tasks(self) -> dict[str, int]:
        with self._connect() as conn:
            cur = conn.cursor()
            attempts = cur.execute("SELECT COUNT(*) FROM callback_attempts").fetchone()[0]
            tasks = cur.execute("SELECT COUNT(*) FROM callback_tasks").fetchone()[0]
            cur.execute("DELETE FROM callback_attempts")
            cur.execute("DELETE FROM callback_tasks")
        return {"tasks": int(tasks), "attempts": int(attempts)}

    def clear_cdr(self) -> dict[str, int]:
        with self._connect() as conn:
            cur = conn.cursor()
            calls = cur.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            segments = cur.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            cur.execute("DELETE FROM segments")
            cur.execute("DELETE FROM calls")
        return {"calls": int(calls), "segments": int(segments)}

    def add_callback_attempt(
        self,
        task_id: int,
        attempt_number: int,
        status: str,
        channel: str | None = None,
        duration: int = 0,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO callback_attempts (
                    task_id, attempt_number, status, channel, duration,
                    error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    attempt_number,
                    status,
                    channel,
                    max(0, duration),
                    error_message,
                    _now_str(),
                ),
            )
            conn.commit()

    def get_callback_statistics(self, days: int = 7) -> dict[str, Any]:
        since = (datetime.now() - timedelta(days=max(1, days))).strftime(
            DATETIME_FORMAT
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                    AVG(delay_seconds) AS avg_delay
                FROM callback_tasks
                WHERE created_at >= ?
                """,
                (since,),
            )
            row = cursor.fetchone()

        total = int(row["total"] or 0)
        completed = int(row["completed"] or 0)
        return {
            "total": total,
            "completed": completed,
            "failed": int(row["failed"] or 0),
            "pending": int(row["pending"] or 0),
            "in_progress": int(row["in_progress"] or 0),
            "cancelled": int(row["cancelled"] or 0),
            "avg_delay": round(float(row["avg_delay"] or 0), 2),
            "success_rate": round((completed / total * 100), 2) if total else 0.0,
        }

    def get_callback_analytics(self, days: int = 7) -> dict[str, Any]:
        days = max(1, int(days))
        since = (datetime.now() - timedelta(days=days)).strftime(DATETIME_FORMAT)
        result: dict[str, Any] = {"days": days}
        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute(
                """
                SELECT status, COUNT(*) AS cnt FROM callback_tasks
                WHERE created_at >= ? GROUP BY status
                """,
                (since,),
            )
            sc = {row["status"]: row["cnt"] for row in cur.fetchall()}
            completed = sc.get("completed", 0)
            failed = sc.get("failed", 0)
            finished = completed + failed
            total = sum(sc.values())
            result["summary"] = {
                "total": total,
                "completed": completed,
                "failed": failed,
                "pending": sc.get("pending", 0),
                "in_progress": sc.get("in_progress", 0),
                "cancelled": sc.get("cancelled", 0),
                "success_rate": round(completed * 100.0 / finished, 1) if finished else 0.0,
            }

            cur.execute(
                """
                SELECT substr(created_at,1,10) AS day,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                       COUNT(*) AS total
                FROM callback_tasks WHERE created_at >= ?
                GROUP BY day ORDER BY day ASC
                """,
                (since,),
            )
            result["daily"] = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT CAST(substr(created_at,12,2) AS INTEGER) AS hour, COUNT(*) AS cnt
                FROM callback_attempts WHERE created_at >= ?
                GROUP BY hour ORDER BY hour ASC
                """,
                (since,),
            )
            hourly = [0] * 24
            for r in cur.fetchall():
                h = r["hour"]
                if h is not None and 0 <= h < 24:
                    hourly[h] = r["cnt"]
            result["hourly"] = hourly

            cur.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(error_message), ''), 'Не указано') AS reason,
                       COUNT(*) AS cnt
                FROM callback_attempts
                WHERE created_at >= ? AND status != 'completed'
                GROUP BY reason ORDER BY cnt DESC LIMIT 8
                """,
                (since,),
            )
            result["failure_reasons"] = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT (retry_count + 1) AS attempts, COUNT(*) AS cnt
                FROM callback_tasks
                WHERE created_at >= ? AND status='completed'
                GROUP BY attempts ORDER BY attempts ASC
                """,
                (since,),
            )
            dist = [dict(r) for r in cur.fetchall()]
            result["attempts_distribution"] = dist
            ta = sum(d["attempts"] * d["cnt"] for d in dist)
            tc = sum(d["cnt"] for d in dist)
            result["avg_attempts_to_success"] = round(ta / tc, 2) if tc else 0.0

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM callback_attempts WHERE created_at >= ?",
                (since,),
            )
            result["total_attempts"] = cur.fetchone()["cnt"]

        return result

    def get_callback_tasks_by_phone(
        self, phone: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM callback_tasks
                WHERE phone = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (phone, max(1, limit)),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_callback_settings(self, defaults: dict[str, Any]) -> dict[str, Any]:
        merged = dict(defaults)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM callback_settings")
            for row in cursor.fetchall():
                try:
                    merged[row["key"]] = json.loads(row["value"])
                except (json.JSONDecodeError, TypeError):
                    merged[row["key"]] = row["value"]
        return merged

    def update_callback_settings(self, values: dict[str, Any]) -> None:
        if not values:
            return

        now_value = _now_str()
        with self._connect() as conn:
            cursor = conn.cursor()
            for key, value in values.items():
                cursor.execute(
                    """
                    INSERT INTO callback_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (
                        key,
                        json.dumps(value, ensure_ascii=False),
                        now_value,
                    ),
                )
            conn.commit()

    def has_recent_callback(self, phone: str, within_minutes: int) -> bool:
        if within_minutes <= 0:
            return False
        threshold = (
            datetime.now() - timedelta(minutes=within_minutes)
        ).strftime(DATETIME_FORMAT)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM callback_tasks
                WHERE phone = ?
                  AND status IN ('pending', 'in_progress', 'completed')
                  AND created_at >= ?
                """,
                (phone, threshold),
            )
            row = cursor.fetchone()
            return bool(row and row["cnt"] > 0)

    def reschedule_callback_task(self, task_id: int, delay_seconds: int = 0) -> None:
        scheduled_at = (
            datetime.now() + timedelta(seconds=max(0, int(delay_seconds)))
        ).strftime(DATETIME_FORMAT)
        now_value = _now_str()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE callback_tasks
                SET status = 'pending', scheduled_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (scheduled_at, now_value, task_id),
            )
            conn.commit()

    def get_callback_attempts(self, task_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM callback_attempts
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            )
            return [dict(row) for row in cursor.fetchall()]