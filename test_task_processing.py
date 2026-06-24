#!/usr/bin/env python3
"""
Тестирование обработки задачи #7 с детальным логированием
"""
import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from callback.manager import callback_manager
from callback.database import callback_db
from callback.ami_connector import ami_connector

async def main():
    print("=" * 60)
    print("🔍 ДЕТАЛЬНОЕ ТЕСТИРОВАНИЕ ОБРАБОТКИ ЗАДАЧИ #7")
    print("=" * 60)

    # 1. Проверяем задачу в БД
    print("\n1️⃣ ПРОВЕРКА ЗАДАЧИ В БАЗЕ ДАННЫХ:")
    task = callback_db.get_task(7)
    if not task:
        print("❌ Задача #7 не найдена в БД!")
        return

    print(f"✅ Задача найдена:")
    print(f"   ID: {task['id']}")
    print(f"   Phone: {task['phone']}")
    print(f"   Status: {task['status']}")
    print(f"   Created: {task['created_at']}")
    print(f"   Scheduled: {task.get('scheduled_time', 'N/A')}")

    # 2. Проверяем подключение к AMI
    print("\n2️⃣ ПРОВЕРКА ПОДКЛЮЧЕНИЯ К AMI:")
    if not await ami_connector.connect():
        print("❌ Не удалось подключиться к AMI")
        return
    print("✅ AMI подключен успешно")

    # 3. Проверяем статус устройства 302
    print("\n3️⃣ ПРОВЕРКА СТАТУСА УСТРОЙСТВА 302:")
    dev_status = await ami_connector.get_device_status('302')
    print(f"Статус устройства 302: {dev_status}")

    # 4. Проверяем, есть ли активные вызовы
    print("\n4️⃣ ПРОВЕРКА АКТИВНЫХ ВЫЗОВОВ:")
    active_calls = await ami_connector.get_active_calls()
    print(f"Активных вызовов: {len(active_calls)}")
    for call in active_calls[:3]:
        print(f"   - {call}")

    # 5. Выполняем обработку задачи вручную с логированием
    print("\n5️⃣ ВЫПОЛНЕНИЕ ОБРАБОТКИ ЗАДАЧИ ВРУЧНУЮ:")
    
    # Обновляем статус задачи на PROCESSING
    callback_db.update_task_status(7, 'processing')
    print("   ✅ Статус обновлен на 'processing'")

    # Выполняем originate
    print("   📞 Попытка вызвать номер 302...")
    result = await ami_connector.originate(
        channel='SIP/302',
        context='from-internal',
        extension='302',
        priority=1,
        caller_id='Callback',
        timeout=30
    )

    if result and result.startswith('originate_'):
        print(f"   ✅ Originate успешно отправлен: {result}")
        callback_db.update_task_status(7, 'completed')
        print("   ✅ Статус обновлен на 'completed'")
    else:
        print(f"   ❌ Originate вернул ошибку: {result}")
        callback_db.update_task_status(7, 'failed')
        print("   ❌ Статус обновлен на 'failed'")

    # 6. Проверяем обновленный статус
    print("\n6️⃣ ФИНАЛЬНАЯ ПРОВЕРКА СТАТУСА:")
    updated_task = callback_db.get_task(7)
    print(f"   Статус задачи: {updated_task['status']}")

    await ami_connector.disconnect()
    print("\n✅ Тестирование завершено")

if __name__ == "__main__":
    asyncio.run(main())
