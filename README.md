# MikoPBX CDR Callback Service

Сервис автоматического **обратного звонка (callback)** для MikoPBX.
Отслеживает пропущенные звонки и сообщения голосовой почты по данным CDR,
автоматически создаёт задачи перезвона и через **AMI (Asterisk Manager
Interface)** инициирует звонок клиенту, соединяя его с очередью или
конкретным оператором.

Написано на Python 3.12 + Flask. Рассчитано на работу как фоновый сервис
на Linux-сервере (systemd).

---

## Возможности

- 📞 **Автодетект пропущенных** — фоновый коллектор читает CDR MikoPBX и
  создаёт задачи callback по событиям `NOANSWER` / `VOICEMAIL`.
- 🔁 **Гибкая маршрутизация** — перезвон в **очередь** (queue) или на
  **конкретного оператора** (direct extension); переключается из UI.
- ⏱ **Настраиваемые тайминги** — отдельные задержки для пропущенных и
  голосовой почты, интервал и число повторов, окно анти-дубликатов.
- 🕐 **Рабочие часы** — звонки только в заданные часы/дни недели.
- 🔌 **Собственный AMI-клиент** на raw-сокете (см. ниже «Почему не
  asterisk-ami»).
- 🖥 **Веб-интерфейс** — панель настроек, живая таблица задач (автообновление),
  статистика, ручное управление (позвонить сейчас / повторить / история).
- 🔁 **Backoff-ретраи** — нарастающие паузы между попытками (`5,15,30…` мин),
  стоп после `max_retries`.
- 🛡 **Защита от перегрузки (anti-storm)** — лимит исходящих в минуту и за
  цикл, чтобы не «положить» транк.
- 🚦 **Проверка занятости оператора** — перед звонком опрашивается состояние
  оператора через AMI `ExtensionState`; если занят/недоступен — заявка
  откладывается без расхода попытки.
- 📊 **Дашборд аналитики** — success rate, нагрузка по часам, причины неудач,
  распределение попыток (графики Chart.js).
- 🔐 **Авторизация** — единый пароль на весь UI и API.
- 🗃 **SQLite** — без внешней БД, всё хранится локально.

---

## Архитектура

```
┌──────────────┐   CDR REST API    ┌─────────────────────┐
│   MikoPBX    │ ◀──────────────── │  Collector (поток)  │  читает пропущенные
│ 10.x.x.x     │                   └─────────┬───────────┘  → создаёт задачи
│              │                             │
│  AMI :5038   │ ◀── Originate ──┐  ┌────────▼───────────┐
└──────────────┘                 └──│ Callback Executor  │  берёт задачи,
                                    │   (поток)          │  звонит, повторяет
                                    └─────────┬──────────┘
                                              │
                                    ┌─────────▼──────────┐
                                    │  SQLite (data/)    │
                                    └─────────┬──────────┘
                                              │
                                    ┌─────────▼──────────┐
                                    │  Flask Web UI/API  │  :5000
                                    └────────────────────┘
```

Модули (`mikoapi/`):

| Файл | Назначение |
|---|---|
| `config.py`   | Конфигурация из `.env` (dataclasses) |
| `database.py` | Схема SQLite, задачи, попытки, настройки |
| `pbx.py`      | Клиент REST API MikoPBX (чтение CDR) |
| `collector.py`| Фоновый сбор пропущенных → создание задач |
| `callback.py` | **AMI-клиент + исполнитель callback** |
| `web.py`      | Flask: веб-UI и REST API |

---

## Схема звонка (callback)

Используется корректная **одно-leg** схема originate:

1. Сервис набирает **номер клиента** каналом `Local/{phone}@<outbound-context>`.
2. Когда клиент **отвечает**, его звонок направляется в `context/exten`
   назначения — это **очередь** (режим queue) или **оператор** (режим direct).
3. При недозвоне — повтор до `max_retries` по **backoff-расписанию**
   (`retry_backoff_minutes`, напр. `5,15,30`). Дубли в окне
   `dedup_window_minutes` отсекаются. Перед каждым звонком проверяются
   лимиты anti-storm и (опционально) занятость оператора.

> ⚠️ **Важно про контексты Asterisk/MikoPBX.** Канал клиента и точка
> назначения живут в **разных контекстах** диалплана:
> - внешний номер набирается через **исходящий контекст** (на нашей АТС —
>   `outgoing`, где паттерн `^(7|8)[0-9]{10}$` уходит в SIP-транк);
> - очередь/оператор находятся в контексте `internal`.
>
> Поэтому `client_channel_template = Local/{phone}@outgoing`, а
> `CALLBACK_CONTEXT = internal`. На вашей АТС имена контекстов могут
> отличаться — проверьте диалплан (`asterisk -rx "dialplan show <exten>@<context>"`).

### Почему собственный AMI-клиент, а не `asterisk-ami`

MikoPBX отдаёт нестандартный приветственный баннер AMI
(`PBX Call Manager` вместо `Asterisk Call Manager`). Библиотека
`asterisk-ami` на этом падает в listen-потоке (`raise Exception()`),
ответ логина теряется, Originate не уходит. Поэтому в `callback.py`
реализован минимальный `SimpleAMIClient` поверх `socket` — он сам
читает баннер, логинится и шлёт `Action: Originate`, корректно сопоставляя
ответ по `ActionID`.

---

## Требования

- Python **3.12+**
- MikoPBX с включённым **AMI** (порт 5038) и **REST API**
- Учётка AMI с правом `originate` и доступом с IP сервиса
- Linux (рекомендуется) или Windows для разработки

---

## Установка (Linux)

```bash
# 1. Клонирование
git clone https://github.com/zangetsuka/mikopbx-CDRcallback.git
cd mikopbx-CDRcallback

# 2. Виртуальное окружение
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Зависимости
pip install -r requirements.txt

# 4. Конфигурация
cp .env.example .env
nano .env        # заполните реальные значения (см. ниже)

# 5. Запуск
python -m mikoapi
```

Веб-интерфейс: `http://<server>:5000`

### Автозапуск через systemd

Создайте `/etc/systemd/system/mikoapi.service`:

```ini
[Unit]
Description=MikoPBX CDR Callback Service
After=network.target

[Service]
Type=simple
User=mikoapi
WorkingDirectory=/opt/mikopbx-CDRcallback
ExecStart=/opt/mikopbx-CDRcallback/.venv/bin/python -m mikoapi
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mikoapi
sudo systemctl status mikoapi
journalctl -u mikoapi -f      # логи
```

---

## Конфигурация (`.env`)

Ключевые параметры (полный список — в `.env.example`):

| Переменная | Описание | Пример |
|---|---|---|
| `MIKO_API_URL`   | URL REST API MikoPBX | `https://10.3.1.28` |
| `MIKO_API_KEY`   | API-ключ MikoPBX | — |
| `MIKO_VERIFY_SSL`| Проверять TLS | `false` |
| `AMI_HOST`       | Хост AMI | `10.3.1.28` |
| `AMI_PORT`       | Порт AMI | `5038` |
| `AMI_USERNAME`   | Логин AMI | `callback_daemon` |
| `AMI_PASSWORD`   | Пароль AMI | — |
| `CALLBACK_QUEUE` | Номер очереди назначения | `2200101` |
| `CALLBACK_CONTEXT`| Контекст назначения (где живёт очередь/оператор) | `internal` |
| `CALLBACK_OPERATOR_EXTENSION` | Оператор для режима direct | `302` |
| `CALLBACK_ORIGINATE_TIMEOUT`  | Таймаут дозвона, сек | `60` |
| `MIKO_WEB_HOST` / `MIKO_WEB_PORT` | Адрес веб-сервера | `0.0.0.0` / `5000` |
| `WEB_AUTH_ENABLED` | Включить вход по паролю | `true` |
| `WEB_AUTH_PASSWORD`| Пароль панели (UI + API) | `admin` |
| `CALLBACK_OWN_DIDS`| Свои городские номера (через запятую) — не перезваниваем | `74812283016` |
| `CALLBACK_CLIENT_NUMBER_REGEX` | Шаблон клиентского номера | `[78]\d{10}` |
| `CALLBACK_MAX_CALL_AGE_MINUTES`| Не перезванивать по пропущенным старше, мин | `60` |

> 🔐 Файл `.env` содержит секреты и **исключён из git** (`.gitignore`).
> В репозитории только шаблон `.env.example`.

### Настройки в UI (хранятся в БД, не в `.env`)

Часть параметров правится «на лету» через веб-панель и сохраняется в SQLite:
`routing_mode` (queue/direct), `client_channel_template`,
`delay_no_answer_minutes`, `delay_voicemail_minutes`, `max_retries`,
`retry_delay_minutes`, `work_hours_*`, `dedup_window_minutes`,
`auto_create`, `enabled`, а также **ретраи и защита**:
`retry_backoff_minutes` (backoff-расписание), `max_calls_per_minute`,
`max_concurrent_calls` (лимит за цикл), `check_operator_busy`,
`busy_check_extension`, `busy_check_context`, `busy_retry_seconds`.

---

## REST API (основное)

| Метод | Endpoint | Назначение |
|---|---|---|
| GET  | `/api/callback/settings` | Текущие настройки |
| POST | `/api/callback/settings` | Обновить настройки |
| GET  | `/api/callback/tasks` | Список задач (фильтры: `status`, `phone`, `limit`) |
| GET  | `/api/callback/stats?days=7` | Статистика |
| GET  | `/api/callback/analytics?days=7` | Аналитика для дашборда (тренды, по часам, причины неудач) |
| POST | `/api/callback/test` | Создать тестовый callback (`{"phone": "..."}`) |
| GET  | `/api/callback/task/<id>/attempts` | История попыток |
| POST | `/api/callback/task/<id>/call-now` | Позвонить немедленно |
| POST | `/api/callback/task/<id>/retry` | Сбросить и повторить |

---

## Структура проекта

```
mikopbx-CDRcallback/
├── mikoapi/
│   ├── __main__.py        # точка входа (python -m mikoapi)
│   ├── config.py          # конфигурация из .env
│   ├── database.py        # SQLite: задачи/попытки/настройки
│   ├── pbx.py             # REST-клиент MikoPBX (CDR)
│   ├── collector.py       # сбор пропущенных
│   ├── callback.py        # AMI-клиент + исполнитель callback
│   ├── web.py             # Flask UI/API
│   ├── static/
│   └── templates/         # callback.html и др.
├── api.json               # OpenAPI-спека MikoPBX (справочник)
├── requirements.txt
├── .env.example
└── README.md
```

## Логи и данные

- SQLite БД: `data/mikoapi.db`
- Логи: `logs/mikoapi.log`

Пути переопределяются через `MIKO_DB_PATH` / `MIKO_LOG_FILE` в `.env`.

---


## Фильтрация номеров (защита от «мусорных» обзвонов)

Чтобы сервис не перезванивал на внутренние номера, сервисные коды или ваши
собственные городские номера, авто-создание заявок фильтрует **номер звонящего**:

- callback создаётся **только** если номер клиента подходит под
  `CALLBACK_CLIENT_NUMBER_REGEX` (по умолчанию `[78]\d{10}` — РФ-формат,
  7/8 + 10 цифр). Внутренние (302) и фичекоды (777, 900) отсекаются автоматически.
- номера из `CALLBACK_OWN_DIDS` (ваши городские DID) **никогда** не
  перезваниваются, даже если попали в поле звонящего.
- `CALLBACK_MAX_CALL_AGE_MINUTES` (по умолчанию 60) — не перезванивать по
  пропущенным **старше** указанного времени. Это предотвращает обзвон всей
  истории CDR при первом запуске сервиса.

## Ретраи и защита от перегрузки

Настраивается в UI (раздел «Ретраи и защита от перегрузки») и хранится в БД:

- **Backoff-ретраи** — `retry_backoff_minutes` задаёт нарастающие паузы между
  попытками, напр. `5,15,30` → 5 мин, затем 15, затем 30 (далее берётся
  последнее значение). Пусто — используется фиксированный `retry_delay_minutes`.
- **Лимит звонков в минуту** (`max_calls_per_minute`) — реальная защита транка:
  не больше N originate за скользящие 60 секунд. `0` — без лимита.
- **Лимит за цикл** (`max_concurrent_calls`) — сколько звонков запускать за один
  тик диспетчера. `0` — без лимита (диспетчер обрабатывает задачи
  последовательно, реальный «потолок» задаёт лимит в минуту).

## Проверка занятости оператора

Если включено `check_operator_busy`, перед звонком сервис опрашивает состояние
оператора через AMI `ExtensionState`:

- номер берётся из `busy_check_extension` (пусто → номер оператора из
  маршрутизации), контекст — `busy_check_context` (по умолчанию `internal`);
- если оператор **занят/недоступен/звонит** — заявка откладывается на
  `busy_retry_seconds` секунд **без расхода попытки**;
- если hint не настроен или AMI недоступен — звонок не блокируется (fail-open).

## Дашборд и аналитика

Главная страница (`/`) показывает аналитику callback:

- KPI: всего заявок, success rate, всего попыток, ср. попыток до успеха, в ожидании;
- графики (Chart.js): заявки по дням, нагрузка по часам, причины неудач,
  распределение «попыток до успеха».

Данные отдаёт `GET /api/callback/analytics?days=N`.

## Авторизация

Весь веб-UI и REST API закрыты единым паролем:

- включается `WEB_AUTH_ENABLED=true`, пароль — `WEB_AUTH_PASSWORD`;
- без входа: HTML-страницы редиректят на `/login`, запросы к `/api/*`
  возвращают `401`;
- вход — `/login`, выход — `/logout` (кнопка «Выйти» в шапке).

> 🔐 Смените дефолтный пароль `admin` перед эксплуатацией. Чтобы сессии не
> сбрасывались при рестарте, задайте стабильный `FLASK_SECRET_KEY` в `.env`.

## Диагностика

| Симптом | Причина / решение |
|---|---|
| `Originate failed (no ActionID)` | AMI вернул ошибку — смотрите лог. Частая причина — неверный контекст/экстеншн. |
| `Extension does not exist` | Контекст в `CALLBACK_CONTEXT` или `client_channel_template` не совпадает с диалпланом АТС. Проверьте `dialplan show`. |
| Звонок не уходит, AMI «молчит» | Проверьте, что AMI включён, креды верны и IP сервиса разрешён в `manager.conf`. |
| Не набирается внешний номер | Канал клиента должен идти через исходящий контекст (`outgoing`), а номер — подходить под паттерн транка. |