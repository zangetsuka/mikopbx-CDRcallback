#!/usr/bin/env python3
"""
Конфигурация системы обратного звонка
"""

import os
from pathlib import Path
from dataclasses import dataclass

# Загружаем .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Загружен .env из {env_path}")
    else:
        print(f"⚠️ .env не найден в {env_path}")
except Exception as e:
    print(f"⚠️ Ошибка загрузки .env: {e}")

@dataclass
class CallbackConfig:
    """Конфигурация обратного звонка"""
    
    # AMI настройки
    ami_host: str = os.getenv("AMI_HOST", "10.3.1.28")
    ami_port: int = int(os.getenv("AMI_PORT", "5038"))
    ami_username: str = os.getenv("AMI_USERNAME", "callback_daemon")
    ami_password: str = os.getenv("AMI_PASSWORD", "CallBack2024!")
    
    # Настройки очереди
    callback_queue: str = os.getenv("CALLBACK_QUEUE", "callback_queue")
    callback_extension: str = os.getenv("CALLBACK_EXTENSION", "callback")
    callback_context: str = os.getenv("CALLBACK_CONTEXT", "from-internal")
    
    # Настройки задержки
    delay_minutes: int = int(os.getenv("CALLBACK_DELAY_MINUTES", "2"))
    max_delay_minutes: int = int(os.getenv("CALLBACK_MAX_DELAY", "5"))
    
    # Настройки уведомлений
    notification_audio: str = os.getenv("CALLBACK_NOTIFICATION_AUDIO", "callback-notification")
    notification_retries: int = int(os.getenv("CALLBACK_NOTIFICATION_RETRIES", "3"))
    notification_interval: int = int(os.getenv("CALLBACK_NOTIFICATION_INTERVAL", "60"))
    
    # Настройки операторов
    min_operators: int = int(os.getenv("CALLBACK_MIN_OPERATORS", "1"))
    max_wait_time: int = int(os.getenv("CALLBACK_MAX_WAIT_TIME", "300"))
    
    # База данных
    db_path: Path = Path(os.getenv("CALLBACK_DB_PATH", "data/callback.db"))
    
    # Логирование
    log_level: str = os.getenv("CALLBACK_LOG_LEVEL", "INFO")
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь"""
        return {
            'ami_host': self.ami_host,
            'ami_port': self.ami_port,
            'callback_queue': self.callback_queue,
            'delay_minutes': self.delay_minutes,
            'notification_audio': self.notification_audio,
            'min_operators': self.min_operators,
            'max_wait_time': self.max_wait_time
        }

# Синглтон конфигурации
config = CallbackConfig()
