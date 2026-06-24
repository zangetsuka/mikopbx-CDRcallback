#!/usr/bin/env python3
"""
AMI Connector для взаимодействия с Asterisk через AMI
"""

import logging
import asyncio
import socket
import time
from typing import Optional, Dict, Any, Callable

from .config import config

logger = logging.getLogger(__name__)

class AMIConnector:
    def __init__(self):
        self._reader = None
        self._writer = None
        self.connected = False
        self.event_handlers = {}

    async def connect(self) -> bool:
        try:
            logger.info(f"🔌 Подключение к AMI {config.ami_host}:{config.ami_port}")

            self._reader, self._writer = await asyncio.open_connection(
                config.ami_host,
                config.ami_port
            )

            login_cmd = f"Action: Login\r\nUsername: {config.ami_username}\r\nSecret: {config.ami_password}\r\n\r\n"
            self._writer.write(login_cmd.encode())
            await self._writer.drain()

            # Читаем ответ
            await asyncio.sleep(0.5)
            response = await self._reader.read(4096)
            response_text = response.decode('utf-8', errors='ignore')
            logger.info(f"AMI Response: {response_text[:200]}...")

            # Проверяем на "Success" в любом месте ответа
            if "Success" in response_text:
                self.connected = True
                logger.info(f"✅ Подключен к AMI {config.ami_host}:{config.ami_port}")
                asyncio.create_task(self._event_loop())
                return True
            else:
                logger.error(f"❌ Ошибка аутентификации AMI: {response_text[:100]}")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка подключения к AMI: {e}")
            return False

    async def disconnect(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        self.connected = False
        logger.info("Отключен от AMI")

    async def _event_loop(self):
        """Цикл обработки событий AMI"""
        while self.connected:
            try:
                data = await self._reader.read(4096)
                if not data:
                    break
                event_text = data.decode('utf-8', errors='ignore')
                
                # Парсим события
                event = {}
                for line in event_text.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        event[key.strip()] = value.strip()
                
                if 'Event' in event:
                    event_name = event['Event']
                    for handler in self.event_handlers.get(event_name, []):
                        try:
                            await handler(event)
                        except Exception as e:
                            logger.error(f"Ошибка в обработчике {event_name}: {e}")
                                
            except Exception as e:
                logger.error(f"Ошибка в цикле событий: {e}")
                await asyncio.sleep(1)

    async def originate(self, 
                       channel: str,
                       context: str,
                       extension: str,
                       priority: int = 1,
                       caller_id: Optional[str] = None,
                       timeout: int = 60,
                       variables: Optional[Dict] = None) -> Optional[str]:
        """Совершить исходящий звонок через AMI"""
        if not self.connected:
            logger.error("AMI не подключен")
            return None
        
        try:
            action_id = f"originate_{int(time.time())}"
            
            cmd = f"""Action: Originate
ActionID: {action_id}
Channel: {channel}
Context: {context}
Exten: {extension}
Priority: {priority}
Timeout: {timeout}
CallerID: {caller_id or extension}
"""
            if variables:
                var_str = ';'.join([f'{k}={v}' for k, v in variables.items()])
                cmd += f"Variable: {var_str}\n"
            
            cmd += "\r\n"
            
            self._writer.write(cmd.encode())
            await self._writer.drain()
            
            logger.info(f"📞 Originate отправлен: {channel} -> {extension}")
            return action_id
            
        except Exception as e:
            logger.error(f"Ошибка при originate: {e}")
            return None

    async def originate_to_queue(self, 
                                 phone: str,
                                 queue: str,
                                 caller_id: Optional[str] = None,
                                 variables: Optional[Dict] = None) -> Optional[str]:
        """Совершить звонок в очередь"""
        channel = f'Local/{queue}@from-queue/n'
        call_vars = {
            'QUEUE': queue,
            'CALLER_ID': caller_id or phone,
            'CALLBACK_PHONE': phone,
            'CALLBACK_TYPE': 'callback'
        }
        if variables:
            call_vars.update(variables)
        
        return await self.originate(
            channel=channel,
            context='from-internal',
            extension=queue,
            priority=1,
            caller_id=caller_id or phone,
            variables=call_vars
        )

    def register_event_handler(self, event_name: str, handler: Callable):
        if event_name not in self.event_handlers:
            self.event_handlers[event_name] = []
        self.event_handlers[event_name].append(handler)

# Синглтон
ami_connector = AMIConnector()
