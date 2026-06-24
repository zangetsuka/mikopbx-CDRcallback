#!/usr/bin/env python3
"""
Принудительное выполнение задачи #7
"""
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from callback.manager import callback_manager
from callback.database import callback_db

async def main():
    print("🔍 Запуск принудительного выполнения задачи #7...")
    
    # Подключаемся к AMI
    if not await callback_manager.start():
        print("❌ Не удалось подключиться к AMI")
        return
    
    # Получаем задачу #7
    task = callback_db.get_task(7)
    if not task:
        print("❌ Задача #7 не найдена")
        await callback_manager.stop()
        return
    
    print(f"📋 Задача #{task['id']}: {task['phone']} (статус: {task['status']})")
    
    # Выполняем задачу
    await callback_manager._execute_task(task)
    
    print("✅ Задача выполнена")
    await callback_manager.stop()

if __name__ == "__main__":
    asyncio.run(main())
