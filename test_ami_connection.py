#!/usr/bin/env python3
"""
Тест подключения к AMI с указанными данными
"""

import socket
import sys
import os
from pathlib import Path

# Загружаем .env
from dotenv import load_dotenv
load_dotenv('/root/mikoapi/.env')

AMI_HOST = os.getenv("AMI_HOST", "10.3.1.28")
AMI_PORT = int(os.getenv("AMI_PORT", "5038"))
AMI_USERNAME = os.getenv("AMI_USERNAME", "callback_daemon")
AMI_PASSWORD = os.getenv("AMI_PASSWORD", "CallBack2024!")

print(f"🔍 Проверка AMI подключения:")
print(f"   Хост: {AMI_HOST}")
print(f"   Порт: {AMI_PORT}")
print(f"   Пользователь: {AMI_USERNAME}")
print(f"   Пароль: {'*' * len(AMI_PASSWORD)}")
print()

# Проверяем доступность порта
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    result = sock.connect_ex((AMI_HOST, AMI_PORT))
    sock.close()
    
    if result == 0:
        print(f"✅ Порт {AMI_PORT} доступен на {AMI_HOST}")
        
        # Пробуем подключиться через telnet и отправить ActionID
        print("\n📡 Пробуем подключиться к AMI...")
        try:
            import telnetlib
            tn = telnetlib.Telnet(AMI_HOST, AMI_PORT)
            
            # Отправляем логин
            tn.write(f"Action: Login\r\nUsername: {AMI_USERNAME}\r\nSecret: {AMI_PASSWORD}\r\n\r\n".encode())
            
            # Ждём ответ
            import time
            time.sleep(1)
            
            # Читаем ответ
            response = tn.read_some()
            print(f"Ответ AMI:\n{response.decode('utf-8', errors='ignore')}")
            
            tn.close()
            
            if "Success" in response.decode('utf-8', errors='ignore'):
                print("\n✅ AMI аутентификация успешна!")
            else:
                print("\n❌ AMI аутентификация не удалась")
                print("   Проверьте логин и пароль")
                
        except Exception as e:
            print(f"❌ Ошибка подключения к AMI: {e}")
            
    else:
        print(f"❌ Порт {AMI_PORT} НЕ доступен на {AMI_HOST}")
        print(f"   Код ошибки: {result}")
        print("\n💡 Проверьте:")
        print("   1. Запущен ли Asterisk/MikoPBX")
        print("   2. Включен ли менеджер в /etc/asterisk/manager.conf")
        print("   3. Правильный ли IP адрес")
        
except Exception as e:
    print(f"❌ Ошибка: {e}")
