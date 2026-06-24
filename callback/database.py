#!/usr/bin/env python3
"""
База данных для системы обратного звонка
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

from .config import config

logger = logging.getLogger(__name__)

class CallbackDatabase:
    """Класс для работы с БД обратного звонка"""
    
    def __init__(self, db_path: Path = config.db_path):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация БД"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица задач обратного звонка
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS callback_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL,
                    call_type TEXT NOT NULL,
                    call_id INTEGER,
                    linkedid TEXT,
                    status TEXT DEFAULT 'pending',
                    priority INTEGER DEFAULT 5,
                    delay_seconds INTEGER DEFAULT 120,
                    operator_extension TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    scheduled_at TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3
                )
            """)
            
            # Таблица попыток звонка
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS callback_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    attempt_number INTEGER,
                    status TEXT,
                    channel TEXT,
                    duration INTEGER,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES callback_tasks(id)
                )
            """)
            
            # Таблица настроек
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS callback_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Создаём индексы
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status 
                ON callback_tasks(status, scheduled_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_phone 
                ON callback_tasks(phone, created_at)
            """)
            
            conn.commit()
            logger.info(f"База данных обратного звонка инициализирована: {self.db_path}")
    
    def create_task(self, phone: str, call_type: str, call_id: Optional[int] = None,
                   linkedid: Optional[str] = None, delay_seconds: int = 120,
                   priority: int = 5, operator_extension: Optional[str] = None) -> int:
        """Создать задачу обратного звонка"""
        scheduled_at = datetime.now() + timedelta(seconds=delay_seconds)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO callback_tasks (
                    phone, call_type, call_id, linkedid, delay_seconds,
                    priority, scheduled_at, operator_extension
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (phone, call_type, call_id, linkedid, delay_seconds, 
                  priority, scheduled_at, operator_extension))
            
            task_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Создана задача обратного звонка #{task_id} для {phone}")
            return task_id
    
    def get_pending_tasks(self) -> List[Dict]:
        """Получить задачи, ожидающие выполнения"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM callback_tasks
                WHERE status = 'pending'
                AND scheduled_at <= datetime('now')
                ORDER BY priority DESC, scheduled_at ASC
            """)
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_task(self, task_id: int) -> Optional[Dict]:
        """Получить задачу по ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT * FROM callback_tasks WHERE id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_task_status(self, task_id: int, status: str, 
                          error_message: Optional[str] = None):
        """Обновить статус задачи"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if status == 'pending':
                cursor.execute(
                    "UPDATE callback_tasks SET status = ? WHERE id = ?",
                    (status, task_id)
                )
            elif status == 'in_progress':
                cursor.execute(
                    "UPDATE callback_tasks SET status = ?, started_at = datetime('now') WHERE id = ?",
                    (status, task_id)
                )
            elif status == 'completed':
                cursor.execute(
                    "UPDATE callback_tasks SET status = ?, completed_at = datetime('now') WHERE id = ?",
                    (status, task_id)
                )
            elif status == 'failed':
                cursor.execute(
                    "UPDATE callback_tasks SET status = ?, error_message = ? WHERE id = ?",
                    (status, error_message, task_id)
                )
            elif status == 'cancelled':
                cursor.execute(
                    "UPDATE callback_tasks SET status = ?, completed_at = datetime('now') WHERE id = ?",
                    (status, task_id)
                )
            
            conn.commit()
    
    def update_task(self, task_id: int, **kwargs):
        """Обновить задачу"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            for key, value in kwargs.items():
                cursor.execute(
                    f"UPDATE callback_tasks SET {key} = ? WHERE id = ?",
                    (value, task_id)
                )
            conn.commit()
    
    def add_attempt(self, task_id: int, attempt_number: int, status: str,
                   channel: Optional[str] = None, duration: int = 0,
                   error_message: Optional[str] = None):
        """Добавить запись о попытке звонка"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO callback_attempts (
                    task_id, attempt_number, status, channel, duration, error_message
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (task_id, attempt_number, status, channel, duration, error_message))
            conn.commit()
    
    def get_statistics(self, days: int = 7) -> Dict:
        """Получить статистику по обратным звонкам"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    AVG(delay_seconds) as avg_delay
                FROM callback_tasks
                WHERE created_at >= datetime('now', ?)
            """, (f'-{days} days',))
            
            stats = cursor.fetchone()
            
            return {
                'total': stats[0] or 0,
                'completed': stats[1] or 0,
                'failed': stats[2] or 0,
                'pending': stats[3] or 0,
                'avg_delay': stats[4] or 0,
                'success_rate': (stats[1] / stats[0] * 100) if stats[0] > 0 else 0
            }
    
    def get_tasks_by_phone(self, phone: str, limit: int = 20) -> List[Dict]:
        """Получить задачи по номеру телефона"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM callback_tasks
                WHERE phone = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (phone, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_tasks(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Получить список задач"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM callback_tasks
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_settings(self) -> Dict:
        """Получить настройки системы"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM callback_settings")
            rows = cursor.fetchall()
            
            settings = {}
            for row in rows:
                try:
                    settings[row['key']] = json.loads(row['value'])
                except:
                    settings[row['key']] = row['value']
            
            return settings
    
    def update_setting(self, key: str, value: Any, description: Optional[str] = None):
        """Обновить настройку"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO callback_settings (key, value, description, updated_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (key, json.dumps(value), description))
            
            conn.commit()

# Синглтон
callback_db = CallbackDatabase()
