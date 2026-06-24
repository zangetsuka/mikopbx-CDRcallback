#!/usr/bin/env python3
"""
Анализатор собранных звонков из базы данных
Показывает статистику и детали по пропущенным звонкам и голосовой почте
"""

import sys
import logging
from datetime import datetime
from tabulate import tabulate

from database import db
from config import CALL_TYPES

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def print_calls_table(calls: list, title: str = "Звонки") -> None:
    """Вывести звонки в виде таблицы"""
    if not calls:
        print("ℹ️ Нет звонков для отображения")
        return

    table_data = []
    for call in calls:
        # Определяем тип звонка
        call_type_display = {
            'no_answer': '❌ Пропущенный',
            'voicemail': '📨 Голосовая почта'
        }.get(call.get('call_type', ''), call.get('call_type', 'N/A'))

        # Форматируем время
        start_time = call.get('start_time', '')
        if start_time:
            try:
                dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S.%f')
                start_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                # Если не удалось распарсить, оставляем как есть
                pass

        table_data.append([
            call.get('id', 'N/A'),
            start_time,
            call.get('src_num', 'N/A'),
            call.get('dst_num', 'N/A'),
            call.get('did', 'N/A'),
            call_type_display,
            call.get('total_duration', 0),
            call.get('voicemail_duration', 0),
            call.get('segment_count', 0)
        ])

    headers = ["ID", "Время", "От", "Кому", "DID", "Тип", "Длит.", "VM Длит.", "Сегм."]
    print(f"\n📋 {title} ({len(calls)}):")
    print(tabulate(table_data, headers=headers, tablefmt="grid"))

def print_statistics(stats: dict, days: int = 7) -> None:
    """Вывести статистику по звонкам"""
    if not stats:
        print("ℹ️ Нет статистики за указанный период")
        return

    print(f"\n📊 СТАТИСТИКА ЗА ПОСЛЕДНИЕ {days} ДНЕЙ")
    print("=" * 60)

    total_calls = 0
    total_voicemail = 0
    total_duration = 0

    for call_type, data in stats.items():
        type_display = {
            'no_answer': '❌ Пропущенные',
            'voicemail': '📨 Голосовая почта'
        }.get(call_type, call_type)

        print(f"\n{type_display}:")
        print(f"   Всего звонков: {data['total']}")
        print(f"   С голосовой почтой: {data['voicemail']}")
        print(f"   Общая длительность: {data['total_duration']}с")
        print(f"   Средняя длительность: {data['avg_duration']}с")

        total_calls += data['total']
        total_voicemail += data['voicemail']
        total_duration += data['total_duration']

    print(f"\n{'=' * 60}")
    print(f"📊 ИТОГО:")
    print(f"   Всего звонков: {total_calls}")
    print(f"   📨 С голосовой почтой: {total_voicemail}")
    if total_calls > 0:
        print(f"   Процент голосовой почты: {total_voicemail / total_calls * 100:.1f}%")
    print(f"   ⏱️  Общая длительность: {total_duration}с")
    print("=" * 60)

def parse_arguments(args: list) -> dict:
    """Парсинг аргументов командной строки"""
    result = {
        'limit': 50,
        'call_type': None,
        'days': 7,
        'show_all': False
    }

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--no-answer" or arg == "-n":
            result['call_type'] = CALL_TYPES['NOANSWER']
        elif arg == "--voicemail" or arg == "-v":
            result['call_type'] = CALL_TYPES['VOICEMAIL']
        elif arg == "--all" or arg == "-a":
            result['show_all'] = True
        elif arg == "--days" and i + 1 < len(args):
            result['days'] = int(args[i + 1])
            i += 1
        elif arg == "--limit" and i + 1 < len(args):
            result['limit'] = int(args[i + 1])
            i += 1
        elif arg == "--help" or arg == "-h":
            print_help()
            return None
        i += 1

    return result

def print_help() -> None:
    """Вывести справку по использованию"""
    print("""
Использование: python3 analyzer.py [ОПЦИИ]

Опции:
  --no-answer, -n     Показать только пропущенные звонки
  --voicemail, -v     Показать только звонки с голосовой почтой
  --all, -a           Показать все звонки
  --days N            Статистика за N дней (по умолчанию 7)
  --limit N           Количество звонков для вывода (по умолчанию 50)
  --help, -h          Показать эту справку

Примеры:
  python3 analyzer.py              # Статистика за 7 дней, последние 50 звонков
  python3 analyzer.py -v           # Только звонки с голосовой почтой
  python3 analyzer.py -n --limit 20 # 20 пропущенных звонков
  python3 analyzer.py --days 1     # Статистика за последний день
    """)

def main() -> None:
    """Основная функция для запуска из командной строки"""
    # Парсинг аргументов
    options = parse_arguments(sys.argv[1:])
    if options is None:  # Была показана справка
        return

    # Если не указан тип и не указано --all, показываем все
    if not options['call_type'] and not options['show_all']:
        options['show_all'] = True

    # Получаем статистику
    stats = db.get_statistics(options['days'])
    print_statistics(stats, options['days'])

    # Получаем и выводим звонки
    if options['show_all']:
        calls = db.get_calls(limit=options['limit'])
        print_calls_table(calls, "Все звонки")
    elif options['call_type']:
        calls = db.get_calls(call_type=options['call_type'], limit=options['limit'])
        type_display = {
            CALL_TYPES['NOANSWER']: "Пропущенные звонки",
            CALL_TYPES['VOICEMAIL']: "Звонки с голосовой почтой"
        }.get(options['call_type'], options['call_type'])
        print_calls_table(calls, type_display)

    # Дополнительная информация
    total = db.get_calls(limit=1)
    if total:
        print(f"\n💡 Для просмотра всех звонков используйте: python3 analyzer.py --all")
        print(f"💡 Для фильтрации по типу: python3 analyzer.py --voicemail или --no-answer")

if __name__ == "__main__":
    main()
