#!/usr/bin/env python3
"""
Веб-интерфейс для MikoPBX Call Analyzer
Flask сервер с дашбордом и визуализацией данных
"""

import os
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
import io

from database import db
from config import CALL_TYPES, DATA_DIR

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
CORS(app)

@app.route('/')
def index():
    """Главная страница - дашборд"""
    return render_template('dashboard.html')

@app.route('/calls')
def calls_page():
    """Страница со списком звонков"""
    return render_template('calls.html')

@app.route('/api/stats')
def api_stats():
    """API: Получить статистику"""
    days = request.args.get('days', 7, type=int)
    stats = db.get_statistics(days)
    
    # Добавляем общую статистику
    total_calls = 0
    total_voicemail = 0
    total_duration = 0
    
    for call_type, data in stats.items():
        total_calls += data['total']
        total_voicemail += data['voicemail']
        total_duration += data['total_duration']
    
    # Получаем статистику по дням
    daily_stats = get_daily_stats(days)
    
    # Получаем общее количество в БД
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
    """API: Получить список звонков с пагинацией и фильтрацией"""
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
    """API: Получить детальную информацию о звонке"""
    from database import db, DB_TABLE_CALLS, DB_TABLE_SEGMENTS
    import sqlite3
    
    try:
        with sqlite3.connect(db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Получаем звонок
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
            
            # Получаем сегменты
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
    """Экспорт данных в CSV"""
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
    """Получить статистику по дням"""
    import sqlite3
    from config import DB_PATH, DB_TABLE_CALLS
    
    daily_data = []
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            for i in range(days):
                date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                
                cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(has_voicemail) as voicemail,
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

@app.route('/api/voicemail/detailed')
def api_voicemail_detailed():
    """API: Детальная статистика по голосовой почте"""
    days = request.args.get('days', 7, type=int)
    
    calls = db.get_calls(call_type='voicemail', limit=1000)
    
    # Анализируем длительность голосовой почты
    durations = [c.get('voicemail_duration', 0) for c in calls]
    
    stats = {
        'total': len(calls),
        'total_duration': sum(durations),
        'avg_duration': sum(durations) / len(durations) if durations else 0,
        'max_duration': max(durations) if durations else 0,
        'min_duration': min(durations) if durations else 0
    }
    
    return jsonify(stats)

def main():
    """Запуск Flask сервера"""
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    print(f"\n🚀 Запуск веб-сервера MikoPBX Analyzer")
    print(f"   http://localhost:{port}")
    print(f"   Нажмите Ctrl+C для остановки\n")
    
    app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    main()
