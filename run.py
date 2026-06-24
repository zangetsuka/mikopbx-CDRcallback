#!/usr/bin/env python3
"""
Единая точка запуска для MikoPBX Callback System
Запускает и веб-сервер, и callback демон в одном процессе
"""

import os
import sys
import logging
import asyncio
import threading
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from callback.manager import callback_manager
from callback.web_api import register_callback_api
from callback.config import config as callback_config
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
from database import db
from config import CALL_TYPES, DATA_DIR
import json
from datetime import datetime, timedelta
import io

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# Flask приложение
# ============================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
CORS(app)

# Регистрируем Callback API
register_callback_api(app)

# ============================================
# Маршруты
# ============================================
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/calls')
def calls_page():
    return render_template('calls.html')

@app.route('/callback')
def callback_page():
    return render_template('callback.html')

@app.route('/api/stats')
def api_stats():
    days = request.args.get('days', 7, type=int)
    stats = db.get_statistics(days)
    total_calls = 0
    total_voicemail = 0
    total_duration = 0
    for call_type, data in stats.items():
        total_calls += data['total']
        total_voicemail += data['voicemail']
        total_duration += data['total_duration']
    daily_stats = get_daily_stats(days)
    total_in_db = db.get_total_count()
    return jsonify({
        'by_type': stats,
        'total': {
            'calls': total_calls,
            'voicemail': total_voicemail,
            'duration': total_duration,
            'total_in_db': total_in_db
        },
        'daily': daily_stats,
        'days': days
    })

@app.route('/api/calls')
def api_calls():
    call_type = request.args.get('type')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    calls = db.get_calls(call_type=call_type, limit=limit, offset=offset)
    total = db.get_total_count()
    return jsonify({
        'calls': calls,
        'total': total,
        'limit': limit,
        'offset': offset
    })

@app.route('/api/call/<int:call_id>')
def api_call_detail(call_id):
    from database import db, DB_TABLE_CALLS, DB_TABLE_SEGMENTS
    import sqlite3
    try:
        with sqlite3.connect(db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT c.*, COUNT(s.id) as segment_count
                FROM {DB_TABLE_CALLS} c
                LEFT JOIN {DB_TABLE_SEGMENTS} s ON c.id = s.call_id
                WHERE c.id = ?
                GROUP BY c.id
            """, (call_id,))
            call = cursor.fetchone()
            if not call:
                return jsonify({'error': 'Call not found'}), 404
            cursor.execute(f"""
                SELECT * FROM {DB_TABLE_SEGMENTS}
                WHERE call_id = ?
                ORDER BY segment_id
            """, (call_id,))
            segments = [dict(row) for row in cursor.fetchall()]
            result = dict(call)
            result['segments'] = segments
            return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/csv')
def export_csv():
    import csv
    calls = db.get_calls(limit=1000)
    output = io.StringIO()
    if calls:
        writer = csv.DictWriter(output, fieldnames=calls[0].keys())
        writer.writeheader()
        writer.writerows(calls)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'calls_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

def get_daily_stats(days: int) -> list:
    import sqlite3
    from config import DB_PATH, DB_TABLE_CALLS
    daily_data = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            for i in range(days):
                date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                cursor.execute(f"""
                    SELECT COUNT(*) as total, SUM(has_voicemail) as voicemail,
                           SUM(total_duration) as duration
                    FROM {DB_TABLE_CALLS}
                    WHERE DATE(start_time) = ?
                """, (date,))
                row = cursor.fetchone()
                daily_data.append({
                    'date': date,
                    'total': row[0] or 0,
                    'voicemail': row[1] or 0,
                    'duration': row[2] or 0
                })
            return daily_data
    except Exception as e:
        app.logger.error(f"Error getting daily stats: {e}")
        return []

# ============================================
# Запуск callback демона в отдельном потоке
# ============================================
def run_callback_daemon():
    """Запуск callback менеджера в отдельном потоке"""
    asyncio.run(callback_manager.start())

# ============================================
# Основная функция
# ============================================
def main():
    """Запуск всего приложения"""
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('WEB_PORT', 5000))
    debug = os.getenv('WEB_DEBUG', 'false').lower() == 'true'
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║     🚀 MikoPBX Callback System - Единый запуск            ║
╠══════════════════════════════════════════════════════════════╣
║  Веб-интерфейс: http://{host if host != '0.0.0.0' else 'localhost'}:{port}       ║
║  Callback демон: запущен в фоновом режиме                 ║
║  Нажмите Ctrl+C для остановки                             ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Запускаем callback демон в отдельном потоке
    callback_thread = threading.Thread(target=run_callback_daemon, daemon=True)
    callback_thread.start()
    
    # Запускаем Flask
    app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    main()
