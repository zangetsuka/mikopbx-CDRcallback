#!/usr/bin/env python3
"""
Тестирование обработки задачи #7 с детальным логированием (исправленная версия)
"""
import sys
import asyncio
from pathlib import Path

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

    # 3. Проверяем активные вызовы (вместо get_device_status)
    print("\n3️⃣ ПРОВЕРКА АКТИВНЫХ ВЫЗОВОВ:")
    active_calls = await ami_connector.get_active_calls()
    print(f"Активных вызовов: {len(active_calls)}")
    if active_calls:
        for call in active_calls[:3]:
            print(f"   - {call}")

    # 4. Проверяем, обрабатывается ли задача в менеджере
    print("\n4️⃣ ПРОВЕРКА ОБРАБОТКИ ЗАДАЧИ ЧЕРЕЗ МЕНЕДЖЕР:")
    
    # Проверяем, есть ли задача в очереди обработки
    pending_tasks = callback_db.get_pending_tasks()
    print(f"   Ожидающих задач в БД: {len(pending_tasks)}")
    for t in pending_tasks[:3]:
        print(f"   - Задача #{t['id']}: {t['phone']} (статус: {t['status']})")
    
    # 5. Выполняем обработку задачи вручную с логированием
    print("\n5️⃣ ВЫПОЛНЕНИЕ ОБРАБОТКИ ЗАДАЧИ ВРУЧНУЮ:")
    
    # Проверяем текущий статус
    if task['status'] == 'completed':
        print(f"   ⚠️ Задача уже завершена (status: {task['status']})")
        print("   ✅ Возможно, задача уже была обработана ранее")
        await ami_connector.disconnect()
        return
    
    # Обновляем статус задачи на PROCESSING
    callback_db.update_task_status(7, 'processing')
    print("   ✅ Статус обновлен на 'processing'")

    # Выполняем originate напрямую
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
