#!/usr/bin/env python3
"""
Менеджер обратного звонка
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any

from .config import config
from .ami_connector import ami_connector
from .database import callback_db

logger = logging.getLogger(__name__)

class CallbackManager:
    def __init__(self):
        self.running = False
        self.task_queue = asyncio.Queue()
        self.active_calls = {}
        
    async def start(self) -> bool:
        if self.running:
            return True
        
        if not await ami_connector.connect():
            logger.error("Не удалось подключиться к AMI")
            return False
        
        self.running = True
        logger.info("Callback Manager запущен")
        
        asyncio.create_task(self._process_queue())
        asyncio.create_task(self._scheduler())
        return True
    
    async def stop(self):
        self.running = False
        await ami_connector.disconnect()
        logger.info("Callback Manager остановлен")
    
    async def add_task(self, phone: str, call_type: str, 
                       call_id: Optional[int] = None,
                       linkedid: Optional[str] = None,
                       delay_seconds: Optional[int] = None,
                       priority: int = 5) -> int:
        if delay_seconds is None:
            delay_seconds = config.delay_minutes * 60
        
        task_id = callback_db.create_task(
            phone=phone,
            call_type=call_type,
            call_id=call_id,
            linkedid=linkedid,
            delay_seconds=delay_seconds,
            priority=priority
        )
        logger.info(f"Задача #{task_id} добавлена для {phone}")
        return task_id
    
    async def _scheduler(self):
        """Планировщик - проверяет задачи каждые 10 секунд"""
        while self.running:
            try:
                pending = callback_db.get_pending_tasks()
                if pending:
                    logger.info(f"📋 Найдено {len(pending)} задач для выполнения")
                    for task in pending:
                        await self.task_queue.put(task)
                        callback_db.update_task_status(task['id'], 'in_progress')
                
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Ошибка в планировщике: {e}")
                await asyncio.sleep(5)
    
    async def _process_queue(self):
        while self.running:
            try:
                task = await self.task_queue.get()
                await self._execute_task(task)
                self.task_queue.task_done()
            except Exception as e:
                logger.error(f"Ошибка обработки задачи: {e}")
                await asyncio.sleep(1)
    
    async def _execute_task(self, task: Dict):
        task_id = task['id']
        phone = task['phone']
        
        logger.info(f"🔄 Выполнение задачи #{task_id} для {phone}")
        
        try:
            # Получаем оператора
            operator = await self._get_available_operator()
            if not operator:
                logger.warning(f"Нет свободных операторов для задачи #{task_id}")
                callback_db.update_task_status(task_id, 'pending', "Нет свободных операторов")
                return
            
            # Выполняем обратный звонок
            result = await self._perform_callback(phone, operator, task)
            
            if result['success']:
                callback_db.update_task_status(task_id, 'completed')
                logger.info(f"✅ Задача #{task_id} успешно выполнена")
            else:
                retry = task.get('retry_count', 0) + 1
                if retry <= task.get('max_retries', 3):
                    callback_db.update_task_status(task_id, 'pending', result.get('error'))
                    logger.warning(f"🔄 Повторная попытка #{task_id} ({retry}/{task.get('max_retries', 3)})")
                else:
                    callback_db.update_task_status(task_id, 'failed', "Превышено количество попыток")
                    logger.error(f"❌ Задача #{task_id} провалена")
                    
        except Exception as e:
            logger.error(f"Ошибка выполнения задачи #{task_id}: {e}")
            callback_db.update_task_status(task_id, 'failed', str(e))
    
    async def _get_available_operator(self) -> Optional[str]:
        return os.getenv("CALLBACK_OPERATOR_EXTENSION", "200")
    
    async def _perform_callback(self, phone: str, operator: str, task: Dict) -> Dict:
        try:
            # Вызываем оператора в очередь
            queue_action = await ami_connector.originate_to_queue(
                phone=operator,
                queue=config.callback_queue,
                caller_id=phone,
                variables={'CALLBACK_TASK_ID': task['id']}
            )
            
            if not queue_action:
                return {'success': False, 'error': 'Не удалось вызвать оператора'}
            
            await asyncio.sleep(2)
            
            # Вызываем клиента
            client_action = await ami_connector.originate(
                channel=f'SIP/{phone}',
                context='from-internal',
                extension=phone,
                priority=1,
                caller_id='Callback',
                variables={'CALLBACK_TASK_ID': task['id']}
            )
            
            if not client_action:
                return {'success': False, 'error': 'Не удалось вызвать клиента'}
            
            await asyncio.sleep(3)
            return {'success': True}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

callback_manager = CallbackManager()
