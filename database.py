#!/usr/bin/env python3
"""
Модуль для работы с базой данных SQLite
"""

import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

from config import DB_PATH, DB_TABLE_CALLS, DB_TABLE_SEGMENTS

# Настройка логирования
logger = logging.getLogger(__name__)

class Database:
    """Класс для работы с базой данных SQLite"""

    def __init__(self, db_path: Path = DB_PATH):
        """Инициализация базы данных"""
        self.db_path = db_path
        self._init_database()

    def _init_database(self) -> None:
        """Инициализация базы данных и создание таблиц"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Таблица звонков
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {DB_TABLE_CALLS} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        linkedid TEXT UNIQUE NOT NULL,
                        src_num TEXT,
                        dst_num TEXT,
                        did TEXT,
                        disposition TEXT,
                        start_time TEXT,
                        total_duration INTEGER,
                        total_billsec INTEGER,
                        call_type TEXT,
                        has_voicemail BOOLEAN DEFAULT 0,
                        voicemail_duration INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        processed BOOLEAN DEFAULT 0
                    )
                """)

                # Таблица сегментов
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {DB_TABLE_SEGMENTS} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        call_id INTEGER,
                        segment_id INTEGER,
                        start_time TEXT,
                        end_time TEXT,
                        src_num TEXT,
                        dst_num TEXT,
                        dst_chan TEXT,
                        disposition TEXT,
                        duration INTEGER,
                        billsec INTEGER,
                        is_voicemail BOOLEAN DEFAULT 0,
                        FOREIGN KEY (call_id) REFERENCES {DB_TABLE_CALLS}(id)
                    )
                """)

                # Индексы для быстрого поиска
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_calls_linkedid
                    ON {DB_TABLE_CALLS}(linkedid)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_calls_start_time
                    ON {DB_TABLE_CALLS}(start_time)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_segments_call_id
                    ON {DB_TABLE_SEGMENTS}(call_id)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_calls_call_type
                    ON {DB_TABLE_CALLS}(call_type)
                """)

                conn.commit()
                logger.info(f"База данных инициализирована: {self.db_path}")

        except sqlite3.Error as e:
            logger.error(f"Ошибка инициализации БД: {e}")
            raise

    def save_call(self, call_data: Dict[str, Any], call_type: str) -> Optional[int]:
        """
        Сохранить звонок в базу данных
        Возвращает ID записи или None если звонок уже существует
        """
        linkedid = call_data.get('linkedid')
        if not linkedid:
            logger.warning("Попытка сохранить звонок без linkedid")
            return None

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Проверяем, есть ли уже такой звонок
                cursor.execute(
                    f"SELECT id FROM {DB_TABLE_CALLS} WHERE linkedid = ?",
                    (linkedid,)
                )
                existing = cursor.fetchone()
                if existing:
                    logger.debug(f"Звонок {linkedid} уже существует в БД")
                    return existing[0]

                # Анализируем звонок
                has_voicemail = False
                voicemail_duration = 0

                for seg in call_data.get('records', []):
                    dst_chan = seg.get('dst_chan', '').lower()
                    if 'voicemail' in dst_chan:
                        has_voicemail = True
                        voicemail_duration += seg.get('duration', 0)

                # Вставляем звонок
                cursor.execute(f"""
                    INSERT INTO {DB_TABLE_CALLS} (
                        linkedid, src_num, dst_num, did, disposition,
                        start_time, total_duration, total_billsec,
                        call_type, has_voicemail, voicemail_duration
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    linkedid,
                    call_data.get('src_num', ''),
                    call_data.get('dst_num', ''),
                    call_data.get('did', ''),
                    call_data.get('disposition', ''),
                    call_data.get('start', ''),
                    call_data.get('totalDuration', 0),
                    call_data.get('totalBillsec', 0),
                    call_type,
                    1 if has_voicemail else 0,
                    voicemail_duration
                ))

                call_id = cursor.lastrowid

                # Сохраняем сегменты
                for seg in call_data.get('records', []):
                    is_voicemail = 'voicemail' in seg.get('dst_chan', '').lower()
                    cursor.execute(f"""
                        INSERT INTO {DB_TABLE_SEGMENTS} (
                            call_id, segment_id, start_time, end_time,
                            src_num, dst_num, dst_chan, disposition,
                            duration, billsec, is_voicemail
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        call_id,
                        seg.get('id'),
                        seg.get('start'),
                        seg.get('endtime'),
                        seg.get('src_num', ''),
                        seg.get('dst_num', ''),
                        seg.get('dst_chan', ''),
                        seg.get('disposition', ''),
                        seg.get('duration', 0),
                        seg.get('billsec', 0),
                        1 if is_voicemail else 0
                    ))

                conn.commit()
                logger.info(f"Сохранен звонок {linkedid} (ID: {call_id}, тип: {call_type})")
                return call_id

        except sqlite3.Error as e:
            logger.error(f"Ошибка сохранения звонка {linkedid}: {e}")
            return None

    def get_calls(self, call_type: Optional[str] = None,
                  limit: int = 100, offset: int = 0) -> List[Dict]:
        """Получить звонки из базы с фильтром по типу"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                query = f"""
                    SELECT c.*, COUNT(s.id) as segment_count
                    FROM {DB_TABLE_CALLS} c
                    LEFT JOIN {DB_TABLE_SEGMENTS} s ON c.id = s.call_id
                """

                params = []
                if call_type:
                    query += " WHERE c.call_type = ?"
                    params.append(call_type)

                query += " GROUP BY c.id ORDER BY c.start_time DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [dict(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"Ошибка получения звонков: {e}")
            return []

    def get_statistics(self, days: int = 7) -> Dict:
        """Получить статистику по звонкам за период"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Используем параметризованный запрос
                query = f"""
                    SELECT
                        call_type,
                        COUNT(*) as total,
                        SUM(has_voicemail) as voicemail_count,
                        SUM(total_duration) as total_duration,
                        AVG(total_duration) as avg_duration
                    FROM {DB_TABLE_CALLS}
                    WHERE start_time >= datetime('now', ?)
                    GROUP BY call_type
                """
                cursor.execute(query, (f'-{days} days',))

                stats = {}
                for row in cursor.fetchall():
                    call_type, total, voicemail, duration, avg = row
                    stats[call_type] = {
                        'total': total,
                        'voicemail': voicemail or 0,
                        'total_duration': duration or 0,
                        'avg_duration': round(avg or 0, 2)
                    }

                return stats

        except sqlite3.Error as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}

    def get_all_linked_ids(self) -> List[str]:
        """Получить все существующие linkedid из БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT linkedid FROM {DB_TABLE_CALLS}")
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения linkedid: {e}")
            return []

    def get_unprocessed_calls(self) -> List[Dict]:
        """Получить необработанные звонки"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT * FROM {DB_TABLE_CALLS}
                    WHERE processed = 0
                    ORDER BY start_time ASC
                """)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения необработанных звонков: {e}")
            return []

    def mark_processed(self, call_id: int) -> bool:
        """Отметить звонок как обработанный"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE {DB_TABLE_CALLS} SET processed = 1 WHERE id = ?",
                    (call_id,)
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка отметки звонка {call_id} как обработанного: {e}")
            return False

    def clear_database(self) -> None:
        """Очистить базу данных (удалить все записи)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"DELETE FROM {DB_TABLE_SEGMENTS}")
                cursor.execute(f"DELETE FROM {DB_TABLE_CALLS}")
                conn.commit()
                logger.info("База данных очищена")
                print("✅ База данных очищена")
        except sqlite3.Error as e:
            logger.error(f"Ошибка очистки БД: {e}")
            print(f"❌ Ошибка очистки БД: {e}")

    def get_total_count(self) -> int:
        """Получить общее количество звонков в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {DB_TABLE_CALLS}")
                return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"Ошибка подсчета звонков: {e}")
            return 0

# Синглтон для использования в других модулях
db = Database()
