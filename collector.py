#!/usr/bin/env python3
"""
Сборщик звонков из MikoPBX API
Сохраняет пропущенные звонки и звонки с голосовой почтой в БД
"""

import time
import sys
import logging
from datetime import datetime
from typing import List, Dict, Set

from config import COLLECT_INTERVAL, CALL_TYPES
from database import db
from checkcdr import CallAnalyzer

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CallCollector:
    """Сборщик звонков из MikoPBX API"""

    def __init__(self):
        self.analyzer = CallAnalyzer()
        self.total_collected = 0
        # Загружаем существующие ID из БД при инициализации
        self._load_existing_ids()

    def _load_existing_ids(self) -> None:
        """Загрузить существующие linkedid из БД"""
        self.existing_ids = set(db.get_all_linked_ids())
        logger.info(f"Загружено {len(self.existing_ids)} существующих ID из БД")

    def collect_calls(self, limit: int = 50) -> int:
        """
        Собрать звонки из API и сохранить в БД

        Args:
            limit: Количество звонков для загрузки

        Returns:
            int: Количество сохраненных звонков
        """
        calls = self.analyzer.get_calls(limit=limit)

        if not calls:
            return 0

        saved_count = 0

        for call in calls:
            linkedid = call.get('linkedid')
            if not linkedid:
                continue

            # Проверяем, не обрабатывали ли мы уже этот звонок
            if linkedid in self.existing_ids:
                continue

            # Анализируем звонок
            analysis = self.analyzer.analyze_call(call)

            # Определяем тип звонка с приоритетом
            call_type = None
            is_no_answer = call.get('disposition') in ['NO ANSWER', 'NOANSWER']
            has_voicemail = analysis['has_voicemail']

            # Приоритет: если есть голосовая почта, классифицируем как voicemail
            if has_voicemail:
                call_type = CALL_TYPES['VOICEMAIL']
            elif is_no_answer:
                call_type = CALL_TYPES['NOANSWER']

            # Если звонок подходит под наши критерии, сохраняем
            if call_type:
                call_id = db.save_call(call, call_type)
                if call_id:
                    saved_count += 1
                    self.existing_ids.add(linkedid)
                    print(f"✅ Сохранен звонок {linkedid} ({call_type})")

        self.total_collected += saved_count
        return saved_count

    def run_once(self, limit: int = 50) -> int:
        """Запустить сбор один раз"""
        print(f"\n📞 Сбор звонков...")
        saved = self.collect_calls(limit)
        total_in_db = db.get_total_count()
        print(f"✅ Сохранено новых звонков: {saved}")
        print(f"📊 Всего в БД: {total_in_db}")
        return saved

    def run_daemon(self, limit: int = 50, interval: int = COLLECT_INTERVAL) -> None:
        """Запустить сбор в режиме демона (периодический сбор)"""
        print(f"\n🔍 ЗАПУСК СБОРА ЗВОНКОВ В ФОНОВОМ РЕЖИМЕ")
        print(f"   Интервал: {interval} секунд")
        print(f"   Лимит звонков за раз: {limit}")
        print(f"   Нажмите Ctrl+C для остановки")
        print("=" * 60)

        try:
            while True:
                saved = self.collect_calls(limit)
                total_in_db = db.get_total_count()
                if saved > 0:
                    print(f"🕐 {datetime.now().strftime('%H:%M:%S')} - Сохранено: {saved}, Всего в БД: {total_in_db}")
                else:
                    print(f"🕐 {datetime.now().strftime('%H:%M:%S')} - Новых звонков нет (всего: {total_in_db})")

                time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n\n👋 Сбор остановлен. Всего в БД: {db.get_total_count()}")
            sys.exit(0)

def main() -> None:
    """Основная функция для запуска из командной строки"""
    collector = CallCollector()

    # Обычный режим - один раз
    if len(sys.argv) == 1:
        collector.run_once()
        return

    # Режимы
    if sys.argv[1] == "--daemon" or sys.argv[1] == "-d":
        interval = COLLECT_INTERVAL
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            interval = int(sys.argv[2])
        collector.run_daemon(interval=interval)
    elif sys.argv[1] == "--limit" and len(sys.argv) > 2:
        limit = int(sys.argv[2])
        collector.run_once(limit)
    elif sys.argv[1] == "--clear":
        db.clear_database()
        collector._load_existing_ids()  # Обновляем кэш
    elif sys.argv[1] == "--help" or sys.argv[1] == "-h":
        print("""
Использование: python3 collector.py [ОПЦИИ]

Опции:
  (без опций)          Запустить сбор один раз (50 звонков)
  --limit N            Собрать N звонков за один раз
  --daemon, -d [СЕК]   Запустить в фоновом режиме с интервалом СЕК (по умолчанию 30)
  --clear              Очистить базу данных
  --help, -h           Показать эту справку

Примеры:
  python3 collector.py              # Одноразовый сбор
  python3 collector.py --limit 100   # Собрать 100 звонков
  python3 collector.py --daemon      # Фоновый сбор каждые 30 секунд
  python3 collector.py -d 60         # Фоновый сбор каждые 60 секунд
  python3 collector.py --clear       # Очистить базу
        """)
    else:
        print("❌ Неизвестная опция. Используйте --help для справки.")

if __name__ == "__main__":
    main()
