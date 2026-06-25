#!/usr/bin/env python3
"""
Анализатор завершенных звонков MikoPBX
Поддерживает фильтрацию по голосовой почте и мониторинг в реальном времени
"""

import requests
import json
import datetime
import sys
import time
import os
import logging
from typing import List, Dict, Any, Optional

from config import BASE_URL, API_KEY, VERIFY_SSL

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Отключаем предупреждения SSL только для этого модуля
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class CallAnalyzer:
    """Класс для работы с API MikoPBX и анализа звонков"""

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }

    def get_calls(self, limit: int = 20) -> List[Dict]:
        """
        Получить последние N звонков из CDR

        Args:
            limit: Количество звонков (макс. 100)

        Returns:
            List[Dict]: Список звонков
        """
        url = f"{BASE_URL}/pbxcore/api/v3/cdr"
        params = {"limit": min(limit, 100)}  # Ограничиваем макс. 100

        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                verify=VERIFY_SSL,
                timeout=30
            )

            if response.status_code != 200:
                logger.error(f"HTTP ошибка: {response.status_code}")
                logger.debug(f"Response: {response.text}")
                return []

            data = response.json()

            if not data.get("result"):
                error_msg = data.get('messages', {}).get('error', 'Неизвестная ошибка')
                logger.error(f"API ошибка: {error_msg}")
                return []

            cdr_data = data.get("data", {})
            records = cdr_data.get("records", [])

            logger.info(f"Получено {len(records)} звонков из API")
            return records

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка соединения с API: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return []

    def analyze_call(self, call: Dict) -> Dict:
        """
        Анализ звонка и классификация сегментов

        Args:
            call: Данные звонка из API

        Returns:
            Dict: Результаты анализа
        """
        segments = call.get("records", [])

        voicemail_segments = []
        queue_segments = []
        sip_segments = []

        for seg in segments:
            dst_chan = seg.get("dst_chan", "").lower()
            dst_num = seg.get("dst_num", "")

            if "voicemail" in dst_chan:
                voicemail_segments.append(seg)
            elif "queue" in dst_chan:
                queue_segments.append(seg)
            elif "pjsip" in dst_chan or "sip" in dst_chan:
                sip_segments.append(seg)

        return {
            "linkedid": call.get("linkedid"),
            "src_num": call.get("src_num"),
            "dst_num": call.get("dst_num"),
            "did": call.get("did"),
            "disposition": call.get("disposition"),
            "totalDuration": call.get("totalDuration", 0),
            "totalBillsec": call.get("totalBillsec", 0),
            "start": call.get("start"),
            "segments": segments,
            "has_voicemail": len(voicemail_segments) > 0,
            "voicemail_count": len(voicemail_segments),
            "voicemail_segments": voicemail_segments,
            "queue_count": len(queue_segments),
            "sip_count": len(sip_segments),
            "segment_count": len(segments)
        }

    def format_segment(self, seg: Dict, show_emoji: bool = True) -> str:
        """Форматирование сегмента для вывода"""
        dst_chan = seg.get('dst_chan', '')
        dst_num = seg.get('dst_num', '')
        disp = seg.get('disposition', '')
        dur = seg.get('duration', 0)

        if 'voicemail' in dst_chan.lower():
            seg_type = "📨 Голосовая почта"
            emoji = "✅" if show_emoji else ""
        elif 'queue' in dst_chan.lower():
            seg_type = "📋 Очередь"
            emoji = ""
        elif 'pjsip' in dst_chan.lower() or 'sip' in dst_chan.lower():
            seg_type = "📞 SIP"
            emoji = ""
        else:
            seg_type = dst_chan
            emoji = ""

        if show_emoji and emoji:
            return f"      {emoji} {seg_type}: {dst_num} ({disp}, {dur}с)"
        else:
            return f"      {seg_type}: {dst_num} ({disp}, {dur}с)"

    def print_call(self, call: Dict, index: int, show_all: bool = True) -> bool:
        """
        Вывод информации о звонке

        Returns:
            bool: True если звонок был показан
        """
        analysis = self.analyze_call(call)

        # Пропускаем звонки без голосовой почты если включен фильтр
        if not show_all and not analysis["has_voicemail"]:
            return False

        status_emoji = {
            "ANSWERED": "✅",
            "NO ANSWER": "❌",
            "NOANSWER": "❌",
            "BUSY": "📞",
            "FAILED": "💥"
        }.get(analysis["disposition"], "❓")

        # Форматируем время
        start_time = analysis['start']
        if start_time:
            try:
                dt = datetime.datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S.%f')
                start_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                pass

        print(f"\n{status_emoji} Звонок #{index + 1}")
        print(f"   🕐 {start_time or 'N/A'}")
        print(f"   📞 {analysis['src_num'] or 'N/A'} → {analysis['dst_num'] or 'N/A'}")
        if analysis['did']:
            print(f"   📞 DID: {analysis['did']}")
        print(f"   📊 Статус: {analysis['disposition'] or 'N/A'}")
        print(f"   ⏱️  Длительность: {analysis['totalDuration']}с")

        # Вывод информации о сегментах
        if analysis['segment_count'] > 0:
            print(f"   📌 Сегменты: {analysis['segment_count']}")
            for seg in analysis['segments']:
                print(self.format_segment(seg))

        # Дополнительная информация
        if analysis["has_voicemail"]:
            print(f"   📨 ПЕРЕАДРЕСОВАНО НА ГОЛОСОВУЮ ПОЧТУ")
            vm_duration = sum(seg.get('duration', 0) for seg in analysis['voicemail_segments'])
            print(f"   📨 Длительность голосовой почты: {vm_duration}с")

        if analysis["queue_count"] > 0 and not analysis["has_voicemail"]:
            print(f"   📋 Звонок в очереди (не переадресован)")

        print("-" * 50)
        return True

    def get_stats(self, calls: List[Dict], show_all: bool = True) -> None:
        """Вывод статистики по звонкам"""
        if not calls:
            return

        # Фильтруем если нужно
        filtered_calls = calls
        if not show_all:
            filtered_calls = [c for c in calls if self.analyze_call(c)["has_voicemail"]]

        if not filtered_calls:
            print("\n📨 Нет звонков с голосовой почтой")
            return

        total = len(filtered_calls)
        voicemail_calls = 0
        queue_calls = 0
        answered = 0

        for call in filtered_calls:
            analysis = self.analyze_call(call)
            if analysis["has_voicemail"]:
                voicemail_calls += 1
            if analysis["queue_count"] > 0:
                queue_calls += 1
            if analysis["disposition"] == "ANSWERED":
                answered += 1

        print(f"\n{'=' * 60}")
        print(f"📊 СТАТИСТИКА ЗАВЕРШЕННЫХ ЗВОНКОВ:")
        print(f"   Всего: {total}")
        if total > 0:
            print(f"   ✅ Отвечено: {answered} ({answered/total*100:.1f}%)")
            print(f"   📨 Переадресовано на голосовую почту: {voicemail_calls} ({voicemail_calls/total*100:.1f}%)")
            print(f"   📋 В очереди: {queue_calls} ({queue_calls/total*100:.1f}%)")
        print(f"{'=' * 60}")

def monitor_calls(analyzer: CallAnalyzer, limit: int = 20, interval: int = 10) -> None:
    """Мониторинг звонков в реальном времени"""
    print(f"\n🔍 МОНИТОРИНГ ЗВОНКОВ В РЕАЛЬНОМ ВРЕМЕНИ")
    print(f"   Интервал обновления: {interval} секунд")
    print(f"   Отображаются только новые звонки")
    print(f"   Нажмите Ctrl+C для выхода")
    print("=" * 60)

    seen_ids = set()
    first_run = True

    try:
        while True:
            # Получаем свежие звонки
            calls = analyzer.get_calls(limit=limit)

            if not calls:
                if first_run:
                    print("ℹ️ Нет звонков для отображения")
                time.sleep(interval)
                first_run = False
                continue

            # Находим новые звонки
            new_calls = []
            for call in calls:
                linked_id = call.get('linkedid')
                if linked_id and linked_id not in seen_ids:
                    new_calls.append(call)
                    seen_ids.add(linked_id)

            # Если есть новые звонки, показываем их
            if new_calls:
                print(f"\n🔄 НОВЫЕ ЗВОНКИ ({len(new_calls)}) - {datetime.datetime.now().strftime('%H:%M:%S')}")
                print("-" * 40)

                for i, call in enumerate(reversed(new_calls)):
                    analyzer.print_call(call, i, show_all=True)

            # При первом запуске показываем последние звонки
            if first_run:
                print(f"\n📋 ПОСЛЕДНИЕ {min(limit, len(calls))} ЗВОНКОВ")
                print("-" * 40)
                for i, call in enumerate(calls[:limit]):
                    analyzer.print_call(call, i, show_all=True)
                first_run = False

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n👋 Мониторинг остановлен")
        sys.exit(0)

def main() -> None:
    """Основная функция для запуска из командной строки"""
    analyzer = CallAnalyzer()

    # Парсинг аргументов командной строки
    args = sys.argv[1:]
    limit = 20
    voicemail_only = False
    watch_mode = False
    watch_interval = 10

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--voicemail-only" or arg == "-v":
            voicemail_only = True
        elif arg == "--watch" or arg == "-w":
            watch_mode = True
            if i + 1 < len(args) and args[i + 1].isdigit():
                watch_interval = int(args[i + 1])
                i += 1
        elif arg.isdigit():
            limit = int(arg)
        elif arg == "--help" or arg == "-h":
            print("""
Использование: python3 checkcdr.py [ОПЦИИ] [ЛИМИТ]

Опции:
  --voicemail-only, -v    Показывать только звонки с голосовой почтой
  --watch, -w [СЕКУНДЫ]   Мониторинг в реальном времени (интервал обновления)
  --help, -h              Показать эту справку

Примеры:
  python3 checkcdr.py              # Последние 20 звонков
  python3 checkcdr.py 50           # Последние 50 звонков
  python3 checkcdr.py -v           # Только звонки с голосовой почтой
  python3 checkcdr.py --watch      # Мониторинг каждые 10 секунд
  python3 checkcdr.py --watch 5    # Мониторинг каждые 5 секунд
  python3 checkcdr.py -v --watch   # Мониторинг только звонков с голосовой почтой
            """)
            return
        i += 1

    # Режим мониторинга
    if watch_mode:
        monitor_calls(analyzer, limit, watch_interval)
        return

    # Обычный режим
    print(f"\n📞 Получение последних {limit} завершенных звонков...")
    calls = analyzer.get_calls(limit=limit)

    if not calls:
        print("❌ Нет звонков")
        return

    # Фильтруем если нужно
    if voicemail_only:
        filtered = [c for c in calls if analyzer.analyze_call(c)["has_voicemail"]]
        print(f"\n📨 Показаны только звонки с голосовой почтой")
        print(f"   Всего звонков: {len(calls)}, с голосовой почтой: {len(filtered)}")
        calls = filtered

    if not calls:
        print("\n❌ Нет звонков для отображения")
        return

    print(f"\n✅ Найдено: {len(calls)} звонков")

    for i, call in enumerate(calls):
        analyzer.print_call(call, i, show_all=not voicemail_only)

    analyzer.get_stats(calls, show_all=not voicemail_only)

if __name__ == "__main__":
    main()
