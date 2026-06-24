#!/usr/bin/env python3
"""
Точка входа для системы обратного звонка
Запуск в режиме демона
"""

import asyncio
import sys
import logging
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from callback.manager import callback_manager
from callback.config import config

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def signal_handler(sig, frame):
    """Обработчик сигналов для корректной остановки"""
    logger.info("Получен сигнал остановки")
    asyncio.create_task(callback_manager.stop())

async def main():
    """Основная функция"""
    logger.info("Запуск Callback System")
    logger.info(f"Конфигурация: {config.to_dict()}")
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await callback_manager.start()
        
        while callback_manager.running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await callback_manager.stop()

if __name__ == "__main__":
    asyncio.run(main())
