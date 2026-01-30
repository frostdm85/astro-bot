#!/usr/bin/env python3
# coding: utf-8

"""
Астро-бот — точка входа
Персональные астрологические прогнозы на основе транзитного анализа
FastAPI + Pyrogram в одном процессе
"""

import asyncio
import logging
import signal
import sys
import threading
from pathlib import Path

# Добавляем src в path
sys.path.insert(0, str(Path(__file__).parent))

from pyrogram import Client, enums, filters
from pyrogram.handlers import MessageHandler

from config import BOT_TOKEN, API_ID, API_HASH, ADMIN_ID

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('astro_bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Инициализация клиента Pyrogram
app = Client(
    "astro_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=str(Path(__file__).parent.parent),
    parse_mode=enums.ParseMode.HTML
)


def register_all_handlers():
    """Регистрация всех обработчиков"""
    from handlers import start, admin, forecast, questions, data_collection, subscription

    start.register_handlers(app)
    admin.register_handlers(app)
    forecast.register_handlers(app)
    questions.register_handlers(app)
    data_collection.register_handlers(app)
    subscription.register_handlers(app)

    logger.info("Все обработчики зарегистрированы")


def start_api_server_thread():
    """Запуск FastAPI сервера в отдельном потоке"""
    import uvicorn
    from api.app import app as fastapi_app

    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)
    server.run()


async def startup():
    """Действия при запуске"""
    logger.info("Запуск Астро-бота...")

    # Инициализация БД
    from database.models import init_db
    init_db()

    # Установка меню команд бота
    from pyrogram.types import BotCommand
    try:
        await app.set_bot_commands([
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("help", "ℹ️ Справка"),
            BotCommand("support", "👨‍💻 Поддержка"),
        ])
        logger.info("Меню команд бота установлено")
    except Exception as e:
        logger.error(f"Не удалось установить меню команд: {e}")

    # Настройка и запуск планировщика
    from services.scheduler import setup_jobs, start_scheduler
    from handlers.forecast import send_daily_forecast
    setup_jobs(app, send_daily_forecast)
    start_scheduler()
    logger.info("Планировщик задач запущен")

    # Уведомление админа
    try:
        await app.send_message(
            ADMIN_ID,
            "🚀 <b>Астро-бот запущен!</b>\n\n"
            "📅 Планировщик: активен\n"
            "🌐 Mini App: https://app.orionastro.ru/webapp"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить админа: {e}")

    logger.info("Бот успешно запущен")


async def shutdown():
    """Действия при остановке"""
    logger.info("Остановка Астро-бота...")

    from services.scheduler import stop_scheduler
    stop_scheduler()
    logger.info("Планировщик остановлен")

    try:
        await app.send_message(ADMIN_ID, "🛑 <b>Астро-бот остановлен</b>")
    except:
        pass

    logger.info("Бот остановлен")


if __name__ == "__main__":
    logger.info("Запуск Астро-бота...")

    # Регистрируем обработчики
    register_all_handlers()

    # Запускаем API сервер в отдельном потоке
    api_thread = threading.Thread(target=start_api_server_thread, daemon=True)
    api_thread.start()
    logger.info("API сервер запущен в отдельном потоке")

    # Инициализация БД
    from database.models import init_db
    init_db()

    # Запускаем планировщик (BackgroundScheduler работает в своём потоке)
    from services.scheduler import setup_jobs, start_scheduler
    from handlers.forecast import send_daily_forecast
    setup_jobs(app, send_daily_forecast)
    start_scheduler()
    logger.info("Планировщик запущен")

    # Запускаем бота через app.run()
    try:
        app.start()
        logger.info("Pyrogram клиент запущен")

        # Отправляем уведомление админу о запуске
        try:
            app.send_message(ADMIN_ID, "🚀 <b>Астро-бот запущен</b>")
            logger.info("Уведомление админу отправлено")
        except Exception as e:
            logger.error(f"Не удалось уведомить админа: {e}")

        logger.info("Бот успешно запущен, ожидаем сообщения...")
        from pyrogram import idle
        idle()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
        try:
            app.send_message(ADMIN_ID, "🛑 <b>Астро-бот остановлен</b>")
        except:
            pass
        app.stop()
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
        try:
            app.send_message(ADMIN_ID, f"❌ <b>Астро-бот упал</b>\n\n{str(e)}")
        except:
            pass
        app.stop()
        sys.exit(1)
