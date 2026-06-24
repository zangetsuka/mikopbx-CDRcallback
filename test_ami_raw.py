#!/usr/bin/env python3
"""
Простой тест AMI - показывает сырой ответ
"""
import socket
import time
import os
from dotenv import load_dotenv

load_dotenv('/root/mikoapi/.env')

AMI_HOST = os.getenv("AMI_HOST", "10.3.1.28")
AMI_PORT = int(os.getenv("AMI_PORT", "5038"))
AMI_USERNAME = os.getenv("AMI_USERNAME", "callback_daemon")
AMI_PASSWORD = os.getenv("AMI_PASSWORD", "CallBack2024!")

print(f"🔌 Подключение к {AMI_HOST}:{AMI_PORT}")
print(f"👤 Пользователь: {AMI_USERNAME}")

try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((AMI_HOST, AMI_PORT))
    
    # Отправляем логин
    login_cmd = f"Action: Login\r\nUsername: {AMI_USERNAME}\r\nSecret: {AMI_PASSWORD}\r\n\r\n"
    sock.send(login_cmd.encode())
    
    # Читаем ответ
    time.sleep(1)
    response = sock.recv(4096)
    response_text = response.decode('utf-8', errors='ignore')
    
    print("\n📥 Сырой ответ AMI:")
    print("=" * 60)
    print(response_text)
    print("=" * 60)
    
    # Проверяем наличие Success
    if "Success" in response_text:
        print("\n✅ Найдено 'Success' - аутентификация успешна!")
    else:
        print("\n❌ 'Success' не найдено в ответе")
    
    sock.close()
    
except Exception as e:
    print(f"❌ Ошибка: {e}")
