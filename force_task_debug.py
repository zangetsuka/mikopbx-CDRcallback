#!/usr/bin/env python3
"""
Принудительное выполнение задачи #7 с отладкой
"""
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from callback.manager import callback_manager
from callback.database import callback_db
from callback.ami_connector import ami_connector

async def main():
    print("🔍 Запуск с отладкой...")
    
    # Подключаемся к AMI
    if not await ami_connector.connect():
        print("❌ Не удалось подключиться к AMI")
        return
    
    print("✅ Подключены к AMI")
    
    # Проверяем задачу
    task = callback_db.get_task(7)
    if not task:
        print("❌ Задача #7 не найдена")
        await ami_connector.disconnect()
        return
    
    print(f"📋 Задача #{task['id']}: {task['phone']}")
    
    # Пробуем сделать originate напрямую
    print("📞 Тестовый originate на 302...")
    result = await ami_connector.originate(
        channel='SIP/302',
        context='from-internal',
        extension='302',
        priority=1,
        caller_id='Callback'
    )
    
    print(f"Результат originate: {result}")
    
    await ami_connector.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
