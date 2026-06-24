# MikoPBX Call Analyzer & Callback System

Комплексная система для сбора, анализа и управления пропущенными звонками с MikoPBX с функцией обратного звонка.

## 🎯 Основные возможности

- 📞 Автоматический сбор звонков из MikoPBX API
- 🔍 Анализ пропущенных звонков и голосовой почты
- 📱 REST API для интеграции с внешними системами
- 🌐 Веб-интерфейс для просмотра и управления
- 📊 Детальная статистика и фильтрация
- 🔄 Автоматическая дедупликация данных
- 📈 Поддержка периодического сбора (cron)

## 🚀 Быстрый старт

```
# Клонируем проект
cd /opt
git clone https://github.com/zangetsuka/mikopbx-CDRcallback.git mikoapi
cd mikoapi

# Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install -r requirements.txt

# Настраиваем конфигурацию
cp .env.example .env
# Отредактируйте .env, указав свои данные

# Запускаем веб-интерфейс
python3 web.py
```

## 📋 Команды

### Сбор данных

```
python3 collector.py              # Одноразовый сбор
python3 collector.py --daemon     # Фоновый сбор
python3 collector.py --clear      # Очистить БД
```

### Просмотр звонков

```
python3 checkcdr.py               # Последние 20 звонков
python3 checkcdr.py 50            # Последние 50 звонков
python3 checkcdr.py -v            # Только голосовая почта
python3 checkcdr.py --watch       # Мониторинг в реальном времени
```

### Анализ данных

```
python3 analyzer.py               # Статистика за 7 дней
python3 analyzer.py -v            # Только голосовая почта
python3 analyzer.py -n            # Только пропущенные
python3 analyzer.py --days 1      # За последний день
```

### Веб-интерфейс

```
python3 web.py                    # Запуск на порту 5000
python3 web.py --port 8080        # На другом порту
python3 web.py --debug            # Режим отладки
```

## 🌐 REST API

### Получить список звонков

```
GET /api/calls?limit=50&offset=0&type=voicemail
```

### Получить статистику

```
GET /api/stats?days=7
```

### Создать задачу обратного звонка

```
POST /api/callback
{
    "phone": "79261234567",
    "priority": "high"
}
```

### Получить список задач

```
GET /api/tasks
```

## 🔧 Конфигурация

Создайте файл `.env`:

```
# MikoPBX API
MIKO_API_URL=https://your-pbx-ip
MIKO_API_KEY=your-api-key
MIKO_VERIFY_SSL=false

# Параметры сбора
MIKO_COLLECT_INTERVAL=30          # Интервал между сборами (секунды)
MIKO_CALLS_LIMIT=100              # Лимит звонков за один запрос

# Веб-сервер
WEB_HOST=0.0.0.0
WEB_PORT=5000
WEB_DEBUG=false

# База данных
DB_PATH=data/calls.db
```

## 📊 База данных

SQLite база данных с двумя таблицами:

### **calls** - основная информация о звонках

| Поле | Тип | Описание |
|---|---|---|
| linkedid | TEXT (PK) | Уникальный ID звонка |
| src_num | TEXT | Номер звонящего |
| dst_num | TEXT | Номер вызываемого |
| call_type | TEXT | no_answer или voicemail |
| has_voicemail | INTEGER | 0/1 флаг наличия голосовой почты |
| created_at | DATETIME | Время создания записи |

### **segments** - сегменты звонка

| Поле | Тип | Описание |
|---|---|---|
| id | INTEGER (PK) | Уникальный ID |
| linkedid | TEXT | Ссылка на звонок |
| dst_chan | TEXT | Тип канала (Queue, VOICEMAIL, SIP) |
| is_voicemail | INTEGER | 0/1 флаг |
| created_at | DATETIME | Время создания записи |

## 📁 Структура проекта

```
mikoapi/
├── collector.py          # Сбор данных из MikoPBX
├── analyzer.py           # Анализ и статистика
├── checkcdr.py          # Просмотр записей CDR
├── database.py          # Работа с базой данных
├── config.py            # Конфигурация и настройки
├── web.py               # Веб-интерфейс и API
├── requirements.txt     # Python зависимости
├── .env.example         # Пример конфигурации
├── README.md           # Документация
├── static/             # Статические файлы
│   ├── css/
│   ├── js/
│   └── images/
├── templates/          # HTML шаблоны
│   ├── index.html      # Главная страница
│   ├── dashboard.html  # Дашборд
│   └── calls.html      # Список звонков
└── data/               # Директория с БД (создается автоматически)
    └── calls.db        # SQLite база данных
```

## 🔒 Безопасность

- ✅ API ключ хранится в `.env` (игнорируется git)
- ✅ `.env.example` содержит только шаблон
- ✅ Поддержка проверки SSL сертификатов
- ✅ Все чувствительные данные исключены из репозитория

## 📈 Автоматизация

### Crontab для периодического сбора

```
# Сбор каждые 5 минут
*/5 * * * * /opt/mikoapi/venv/bin/python3 /opt/mikoapi/collector.py

# Очистка старых записей раз в неделю
0 3 * * 0 /opt/mikoapi/venv/bin/python3 /opt/mikoapi/collector.py --clear-old 30
```

### Systemd сервис

Создайте `/etc/systemd/system/mikoapi.service`:

```
[Unit]
Description=MikoPBX Call Analyzer
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mikoapi
ExecStart=/opt/mikoapi/venv/bin/python3 /opt/mikoapi/web.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Запуск сервиса:

```
systemctl daemon-reload
systemctl enable mikoapi
systemctl start mikoapi
```

## 🐛 Устранение проблем

### Ошибка подключения к API

- Проверьте `MIKO_API_URL` и `MIKO_API_KEY` в `.env`
- Убедитесь, что сервер MikoPBX доступен
- Проверьте корректность SSL сертификата

### Дублирование звонков

- База данных использует UNIQUE для `linkedid`
- Автоматическая дедупликация при сохранении

### Проблемы с SSL

- Установите `MIKO_VERIFY_SSL=false` для самоподписанных сертификатов

### База данных заблокирована

- SQLite поддерживает одновременное чтение
- Используйте `--timeout` параметр при интенсивной записи

## 🔧 Разработка

### Добавление новых источников данных

1. Создайте новый модуль в `collectors/`
1. Наследуйте от базового класса `BaseCollector`
1. Реализуйте метод `collect()`
1. Добавьте в `collector.py` выбор источника

### Расширение API

1. Добавьте новый роут в `web.py`
1. Используйте декоратор `@app.route()`
1. Документируйте в README

## 📝 Лицензия

MIT License

Copyright (c) 2025 zangetsuka

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 🤝 Вклад

1. Форкните репозиторий
1. Создайте ветку для фичи (`git checkout -b feature/AmazingFeature`)
1. Закоммитьте изменения (`git commit -m 'Add some AmazingFeature'`)
1. Запушьте ветку (`git push origin feature/AmazingFeature`)
1. Откройте Pull Request

## 📞 Контакты

- GitHub: [@zangetsuka](https://github.com/zangetsuka)
- Проект: [MikoPBX Call Analyzer](https://github.com/zangetsuka/mikopbx-CDRcallback)

⭐ Если проект полезен, поставьте звезду!