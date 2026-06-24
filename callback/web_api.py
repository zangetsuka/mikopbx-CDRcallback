#!/usr/bin/env python3
"""
Web API для системы обратного звонка
Интеграция с Flask веб-интерфейсом
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import logging
import asyncio
import threading

from .database import callback_db
from .manager import callback_manager
from .config import config

logger = logging.getLogger(__name__)

# Создаём Blueprint для API
callback_api = Blueprint('callback_api', __name__)

@callback_api.route('/api/callback/tasks', methods=['GET'])
def get_tasks():
    """Получить список задач обратного звонка"""
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    tasks = callback_db.get_tasks(limit=limit, offset=offset)
    
    return jsonify({
        'tasks': tasks,
        'total': len(tasks)
    })

@callback_api.route('/api/callback/task', methods=['POST'])
def create_task():
    """Создать задачу обратного звонка"""
    data = request.get_json()
    
    phone = data.get('phone')
    call_type = data.get('call_type', 'no_answer')
    call_id = data.get('call_id')
    linkedid = data.get('linkedid')
    delay_seconds = data.get('delay_seconds')
    priority = data.get('priority', 5)
    
    if not phone:
        return jsonify({'error': 'Phone number is required'}), 400
    
    phone = phone.strip()
    if not phone.isdigit():
        return jsonify({'error': 'Invalid phone number format'}), 400
    
    task_id = callback_db.create_task(
        phone=phone,
        call_type=call_type,
        call_id=call_id,
        linkedid=linkedid,
        delay_seconds=delay_seconds,
        priority=priority
    )
    
    return jsonify({
        'success': True,
        'task_id': task_id,
        'message': f'Task #{task_id} created for {phone}'
    })

@callback_api.route('/api/callback/task/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """Получить информацию о задаче"""
    task = callback_db.get_task(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(task)

@callback_api.route('/api/callback/task/<int:task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    """Отменить задачу"""
    task = callback_db.get_task(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    if task['status'] not in ['pending', 'in_progress']:
        return jsonify({'error': 'Task cannot be cancelled'}), 400
    
    callback_db.update_task_status(task_id, 'cancelled')
    
    return jsonify({
        'success': True,
        'message': f'Task #{task_id} cancelled'
    })

@callback_api.route('/api/callback/settings', methods=['GET'])
def get_settings():
    """Получить настройки обратного звонка"""
    settings = {
        'delay_minutes': config.delay_minutes,
        'max_delay_minutes': config.max_delay_minutes,
        'notification_audio': config.notification_audio,
        'notification_retries': config.notification_retries,
        'min_operators': config.min_operators,
        'max_wait_time': config.max_wait_time,
        'callback_queue': config.callback_queue
    }
    
    return jsonify(settings)

@callback_api.route('/api/callback/settings', methods=['POST'])
def update_settings():
    """Обновить настройки обратного звонка"""
    data = request.get_json()
    
    for key, value in data.items():
        if hasattr(config, key):
            setattr(config, key, value)
            callback_db.update_setting(key, value)
    
    return jsonify({
        'success': True,
        'message': 'Settings updated'
    })

@callback_api.route('/api/callback/stats', methods=['GET'])
def get_stats():
    """Получить статистику обратного звонка"""
    days = request.args.get('days', 7, type=int)
    stats = callback_db.get_statistics(days)
    
    return jsonify(stats)

@callback_api.route('/api/callback/phone/<phone>', methods=['GET'])
def get_phone_tasks(phone):
    """Получить задачи по номеру телефона"""
    limit = request.args.get('limit', 20, type=int)
    tasks = callback_db.get_tasks_by_phone(phone, limit)
    
    return jsonify({
        'phone': phone,
        'tasks': tasks,
        'total': len(tasks)
    })

@callback_api.route('/api/callback/test', methods=['POST'])
def test_callback():
    """Тестовый вызов обратного звонка"""
    data = request.get_json()
    phone = data.get('phone', '12345')
    
    # Запускаем в отдельном потоке с новым event loop
    def run_async_task():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(callback_manager.add_task(
                phone=phone,
                call_type='test',
                delay_seconds=10
            ))
        finally:
            loop.close()
    
    thread = threading.Thread(target=run_async_task)
    thread.start()
    
    return jsonify({
        'success': True,
        'message': f'Test callback scheduled for {phone}'
    })

def register_callback_api(app):
    """Зарегистрировать API обратного звонка в Flask приложении"""
    app.register_blueprint(callback_api)
    app.config['CALLBACK_ENABLED'] = True
    logger.info("Callback API зарегистрирован")
