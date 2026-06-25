#!/usr/bin/env python3
"""
Конфигурация проекта MikoPBX Call Analyzer
Загружает настройки из переменных окружения (.env)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env файл
BASE_DIR = Path(__file__).parent.parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

# Пути
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "calls.db"

# Создаем директорию для данных
DATA_DIR.mkdir(exist_ok=True)

# API конфигурация (из .env или значения по умолчанию)
BASE_URL = os.getenv("MIKO_API_URL", "https://10.3.1.28")
API_KEY = os.getenv("MIKO_API_KEY", "ae3ee7a2d1bbe063beba7e492873ebe413bafb319a3e5c5e6c278772647d7dda")
VERIFY_SSL = os.getenv("MIKO_VERIFY_SSL", "false").lower() == "true"

# Параметры сбора
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# Типы звонков для сбора
CALL_TYPES = {
    'NOANSWER': 'no_answer',      # Пропущенные звонки
    'VOICEMAIL': 'voicemail',      # Переадресованные на голосовую почту
}

# Интервал сбора в секундах (для мониторинга)
COLLECT_INTERVAL = int(os.getenv("MIKO_COLLECT_INTERVAL", "30"))

# Настройки базы данных
DB_TABLE_CALLS = "calls"
DB_TABLE_SEGMENTS = "segments"

# Настройки логирования
LOG_LEVEL = os.getenv("MIKO_LOG_LEVEL", "INFO")
