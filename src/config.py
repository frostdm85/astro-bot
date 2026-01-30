#!/usr/bin/env python3
# coding: utf-8

"""
Конфигурация Астро-бота
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")

# Groq API
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# YooKassa
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")

# База данных
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "astro_bot.sqlite"))

# Подписка
SUBSCRIPTION_PRICE = int(os.getenv("SUBSCRIPTION_PRICE", 1990))
SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS", 30))

# Лимиты
QUESTIONS_PER_DAY = int(os.getenv("QUESTIONS_PER_DAY", 10))

# Время по умолчанию
DEFAULT_FORECAST_TIME = "09:00"
DEFAULT_TIMEZONE = "Europe/Moscow"

# URL для возврата после оплаты
BOT_USERNAME = os.getenv("BOT_USERNAME", "astro_natal_bot")
BOT_RETURN_URL = f"https://t.me/{BOT_USERNAME}"

# Mini App URL (для локальной разработки — localhost, для прода — публичный URL)
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.com")

# Юридические документы
DOCS_OFFER = "https://disk.yandex.ru/d/CTe2fBbWrwolfg"  # Договор-оферта
DOCS_PD_CONSENT = "https://disk.yandex.ru/i/J8_SAQJ9b5Ewcg"  # Согласие на обработку ПД
DOCS_PRIVACY_POLICY = "https://disk.yandex.ru/i/INC_GXZ5ZzJ1_w"  # Политика обработки ПД
DOCS_MARKETING_CONSENT = "https://disk.yandex.ru/i/TvOndS5KmoUsyw"  # Согласие на рассылку

# Валидация
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env")

if not API_ID or not API_HASH:
    raise ValueError("API_ID и API_HASH должны быть заданы в .env")

if not ADMIN_ID:
    raise ValueError("ADMIN_ID не задан в .env")
