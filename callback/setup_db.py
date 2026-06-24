#!/usr/bin/env python3
"""
Скрипт инициализации базы данных обратного звонка
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from callback.database import callback_db
from callback.config import config

def main():
    """Инициализация БД"""
    print("Инициализация базы данных обратного звонка...")
    print(f"Путь к БД: {config.db_path}")
    
    try:
        callback_db._init_database()
        print("✅ База данных успешно инициализирована")
        
        default_settings = {
            'delay_minutes': config.delay_minutes,
            'notification_audio': config.notification_audio,
            'min_operators': config.min_operators,
            'max_wait_time': config.max_wait_time
        }
        
        for key, value in default_settings.items():
            callback_db.update_setting(key, value, f"Default {key}")
        
        print("✅ Настройки по умолчанию добавлены")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
