# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Астро-бот — Telegram-бот для персональных астрологических прогнозов на основе транзитного анализа по методу С.В. Шестопалова. Включает Mini App (веб-интерфейс) и админ-панель.

**Технологический стек:**
- **Telegram Bot**: Pyrogram (pyrofork)
- **API**: FastAPI + Uvicorn (порт 8080)
- **База данных**: SQLite + Peewee ORM
- **Астрологический движок**: Swiss Ephemeris (pyswisseph)
- **AI**: Groq API (Llama 3.3 70B) для генерации прогнозов
- **TTS**: Edge TTS для озвучки
- **Планировщик**: APScheduler (BackgroundScheduler)

## Commands

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск бота (включает FastAPI сервер в потоке)
cd src && python main.py

# Локальная разработка Mini App
# API доступен на http://localhost:8080
# Mini App: http://localhost:8080/webapp
# Admin: http://localhost:8080/admin

# Отдельная админ-панель (Flask)
cd admin-webapp && pip install -r requirements.txt && python app.py
```

## Architecture

### Структура проекта

```
astro-bot/
├── src/
│   ├── main.py                 # Точка входа: Pyrogram + FastAPI в одном процессе
│   ├── config.py               # Конфигурация из .env
│   ├── api/
│   │   └── app.py              # FastAPI приложение для Mini App
│   ├── database/
│   │   └── models.py           # Peewee ORM модели
│   ├── handlers/
│   │   ├── start.py            # /start, главное меню
│   │   ├── forecast.py         # Генерация и отправка прогнозов
│   │   ├── questions.py        # AI-вопросы пользователей
│   │   └── admin.py            # Админ-панель бота
│   ├── services/
│   │   ├── astro_engine.py     # Swiss Ephemeris расчёты (~900 строк)
│   │   ├── groq_client.py      # Groq API + формулы Шестопалова
│   │   ├── scheduler.py        # APScheduler задачи
│   │   ├── geocoder.py         # Геокодинг городов
│   │   ├── tts_service.py      # Edge TTS озвучка
│   │   └── yookassa_service.py # Платежи YooKassa
│   ├── data/
│   │   ├── shestopalov.py      # Формулы событий Шестопалова
│   │   ├── shestopalov_rules.py
│   │   └── formula_meanings.py # Расшифровка формул
│   ├── utils/
│   │   └── keyboards.py        # Inline-клавиатуры
│   └── webapp/                 # Mini App статика
│       ├── index.html          # Главная страница Mini App
│       ├── admin.html          # Админ-панель (Telegram WebApp)
│       ├── js/app.js           # JavaScript приложение
│       └── css/style.css
├── admin-webapp/               # Отдельная Flask админ-панель
└── requirements.txt
```

### Ключевые компоненты

**1. Запуск приложения (main.py)**
- FastAPI сервер запускается в отдельном daemon-потоке
- Pyrogram бот запускается через `app.run()`
- Планировщик работает в BackgroundScheduler

**2. Астрологический движок (astro_engine.py)**
- `calculate_local_natal()` — расчёт натальной карты с релокацией
- `calculate_transits()` — расчёт транзитов на период
- `calculate_houses()` — расчёт домов (система Koch)
- `get_transits()` — получение транзитов с аспектами
- Использует Julian Day для всех расчётов

**3. Генерация прогнозов (groq_client.py)**
- `generate_forecast()` — AI-генерация на основе формул Шестопалова
- `extract_formula_meanings()` — извлечение значений формул из транзитов
- Retry-логика с экспоненциальной задержкой при ошибках API

**4. Планировщик (scheduler.py)**
- `check_forecast_time()` — ежеминутная проверка времени рассылки (учёт TZ пользователя)
- `check_subscriptions()` — ежедневно в 10:00 (напоминания, истечение)
- `check_important_transits()` — каждые 6 часов (уведомления о тяжёлых планетах)
- `cleanup_stale_fsm_states()` — каждый час (очистка FSM)

**5. API эндпоинты (api/app.py)**
- `/api/forecast/{user_id}/today` — прогноз на сегодня
- `/api/forecast/{user_id}/date/{date_str}` — прогноз на дату
- `/api/forecast/{user_id}/calendar` — календарь месяца с кэшированием
- `/api/natal-chart/{user_id}` — данные для визуализации натальной карты
- `/api/moon` — текущая фаза Луны
- `/api/users/*` — CRUD пользователей (админ)
- Авторизация через `X-Telegram-Init-Data` заголовок

**6. Модели БД (models.py)**
- `User` — пользователи с натальными данными
- `Subscription` — подписки (pending/active/expiring_soon/expired)
- `Forecast` — история прогнозов
- `CalendarCache` — кэш календаря (TTL 30 дней)
- `Conversation` — контекст диалога с AI

### Формулы Шестопалова

Система интерпретации транзитов через номера домов:
- Формула = `X(a,b) + Y(c,d)` где X,Y — дом планеты, (a,b),(c,d) — управляемые дома
- Знак `+` = позитивный аспект (тригон, секстиль)
- Знак `-` = негативный аспект (квадратура, оппозиция)
- Соединение: негативное если одна из планет злая (Марс, Сатурн, Уран, Нептун, Плутон)

## Credentials & Environment

### Данные бота

| Параметр | Значение |
|----------|----------|
| **Bot Username** | @astro_natal_bot |
| **Bot Token** | `8283402095:AAGfDT-dJgA5JcwBbSZyLvwt6v6q0QhD3eY` |
| **API ID** | 28339428 |
| **API Hash** | `ff1d1ac7ccb467b8611aafa1f01a0fbe` |
| **Admin ID** | 1011330674 |
| **Admin Username** | @dmitrystarkov77 |

### Groq API

| Параметр | Значение |
|----------|----------|
| **GROQ_API_KEY** | `gsk_***` (см. .env на сервере) |
| **Model** | llama-3.3-70b-versatile |

### Сервер (192.168.0.24)

| Параметр | Значение |
|----------|----------|
| **Root Password** | `Moroz1985b` |
| **Путь** | `/opt/astro-bot/` |

### .env файл

```bash
# Telegram
BOT_TOKEN=8283402095:AAGfDT-dJgA5JcwBbSZyLvwt6v6q0QhD3eY
API_ID=28339428
API_HASH=ff1d1ac7ccb467b8611aafa1f01a0fbe
ADMIN_ID=1011330674
ADMIN_USERNAME=dmitrystarkov77

# Groq API
GROQ_API_KEY=gsk_***
GROQ_MODEL=llama-3.3-70b-versatile

# YooKassa (заполнить после регистрации)
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=

# База данных
DB_PATH=/opt/astro-bot/src/astro_bot.sqlite

# Подписка
SUBSCRIPTION_PRICE=990
SUBSCRIPTION_DAYS=30

# Лимиты
QUESTIONS_PER_DAY=10
```

## Server Deployment

| Параметр | Значение |
|----------|----------|
| **IP** | 192.168.0.24 |
| **Путь** | /opt/astro-bot/ |
| **Сервис** | astro-bot.service |
| **Mini App URL** | https://app.orionastro.ru/webapp |
| **Admin URL** | https://app.orionastro.ru/admin |
| **API Port** | 8080 |
| **Reverse Proxy** | Orion (192.168.0.16) nginx |

### Команды управления
```bash
# Статус сервиса
systemctl status astro-bot

# Перезапуск
systemctl restart astro-bot

# Логи в реальном времени
journalctl -u astro-bot -f

# Включить автозапуск
systemctl enable astro-bot
```

### Деплой обновлений
```bash
# С локальной машины
scp -r src/* root@192.168.0.24:/opt/astro-bot/src/
ssh root@192.168.0.24 'systemctl restart astro-bot'
```

### Systemd сервисы (порядок запуска)

```
network.target → add-default-route → amneziawg → astro-bot
```

**1. add-default-route.service** — добавляет gateway (Proxmox LXC сбрасывает его)
```ini
[Unit]
Description=Add default gateway route
After=network.target
Before=astro-bot.service

[Service]
Type=oneshot
ExecStart=/sbin/ip route add default via 192.168.0.1
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

**2. amneziawg.service** — VPN для доступа к Groq API (заблокирован в РФ)
```ini
[Unit]
Description=AmneziaWG VPN for Groq API
After=network.target add-default-route.service
Requires=add-default-route.service
Before=astro-bot.service

[Service]
Type=oneshot
# Проверка: если awg0 уже существует — не поднимаем повторно
ExecStart=/bin/bash -c "ip link show awg0 >/dev/null 2>&1 || /usr/bin/awg-quick up awg0"
ExecStop=/usr/bin/awg-quick down awg0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

**3. astro-bot.service** — основной сервис бота
```ini
[Unit]
Description=Astro Bot Telegram Mini App
After=network.target add-default-route.service amneziawg.service
Requires=add-default-route.service amneziawg.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/astro-bot/src
Environment=PATH=/opt/astro-bot/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/astro-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Conventions

- **Часовые пояса**: Натальная карта рассчитывается в TZ места рождения, транзиты отображаются в TZ места проживания
- **Кэш календаря**: Инвалидируется при изменении натальных данных через `CalendarCache.invalidate_for_user()`
- **FSM состояния**: Хранятся в словарях `user_*_states`, очищаются по TTL (1 час)
- **Логирование**: Все модули используют `logging.getLogger(__name__)`
- **Ошибки API**: Человекочитаемые сообщения в `ERROR_MESSAGES` / `API_ERROR_MESSAGES`
