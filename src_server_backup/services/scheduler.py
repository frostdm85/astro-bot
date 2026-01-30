#!/usr/bin/env python3
# coding: utf-8

"""
Планировщик задач для Астро-бота
На основе APScheduler (Context7 документация)

Задачи:
- Ежедневная рассылка прогнозов
- Проверка истекающих подписок
- Уведомления о важных транзитах
"""

import logging
import asyncio
from datetime import datetime, date, timedelta
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Глобальный планировщик
scheduler: Optional[BackgroundScheduler] = None

# Event loop для выполнения async функций из BackgroundScheduler
_scheduler_loop = None


def init_scheduler() -> BackgroundScheduler:
    """Инициализация планировщика"""
    global scheduler

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")

    logger.info("Планировщик инициализирован")
    return scheduler


def start_scheduler():
    """Запуск планировщика"""
    global scheduler

    if scheduler is None:
        scheduler = init_scheduler()

    if not scheduler.running:
        scheduler.start()
        logger.info("Планировщик запущен")


def stop_scheduler():
    """Остановка планировщика"""
    global scheduler

    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("Планировщик остановлен")


async def check_forecast_time(app, send_forecast_func: Callable):
    """
    Проверка времени рассылки прогнозов (вызывается каждую минуту)

    Учитывает часовой пояс каждого пользователя:
    - Получаем текущее время UTC
    - Для каждого пользователя вычисляем локальное время
    - Сравниваем с forecast_time пользователя

    Args:
        app: Pyrogram клиент
        send_forecast_func: Функция отправки прогноза
    """
    from database.models import User
    import pytz

    utc_now = datetime.utcnow()
    logger.debug(f"Проверка времени прогноза: UTC {utc_now.strftime('%H:%M')}")

    # Находим пользователей с активной подпиской и натальными данными
    users = User.select().where(
        User.natal_data_complete == True,
        User.is_active == True
    )

    for user in users:
        if not user.has_active_subscription():
            continue

        try:
            # Определяем часовой пояс пользователя
            tz_name = user.residence_tz or user.birth_tz or "Europe/Moscow"
            try:
                tz = pytz.timezone(tz_name)
                user_now = utc_now.replace(tzinfo=pytz.utc).astimezone(tz)
                user_time = user_now.strftime("%H:%M")
            except Exception:
                # Fallback: MSK (UTC+3)
                user_now = utc_now + timedelta(hours=3)
                user_time = user_now.strftime("%H:%M")

            # Сравниваем с настройкой пользователя
            if user.forecast_time == user_time:
                await send_forecast_func(app, user)
                logger.info(f"Отправлен прогноз пользователю {user.telegram_id} (TZ: {tz_name}, время: {user_time})")
                await asyncio.sleep(0.1)  # Небольшая пауза между отправками

        except Exception as e:
            logger.error(f"Ошибка отправки прогноза {user.telegram_id}: {e}")


async def check_subscriptions(app):
    """
    Проверка статусов подписок (вызывается ежедневно в 10:00)

    - Напоминание за 3 дня до окончания
    - Напоминание в день окончания
    - Обновление статуса истёкших подписок
    """
    from database.models import User, Subscription

    now = datetime.now()
    today = date.today()
    three_days = now + timedelta(days=3)

    logger.info("Проверка подписок...")

    # Подписки, истекающие через 3 дня
    expiring_3d = Subscription.select().where(
        Subscription.status.in_(['active', 'expiring_soon']),
        Subscription.expires_at >= now,
        Subscription.expires_at <= three_days
    )

    for sub in expiring_3d:
        if sub.status != 'expiring_soon':
            sub.status = 'expiring_soon'
            sub.save()

        try:
            days_left = (sub.expires_at - now).days
            await app.send_message(
                sub.user.telegram_id,
                f"⏰ <b>Напоминание</b>\n\n"
                f"Ваша подписка заканчивается через {days_left} дн. ({sub.expires_at.strftime('%d.%m.%Y')}).\n\n"
                f"Продлите подписку, чтобы продолжить получать персональные прогнозы."
            )
            logger.info(f"Напоминание отправлено: {sub.user.telegram_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания: {e}")

    # Истёкшие подписки
    expired = Subscription.select().where(
        Subscription.status.in_(['active', 'expiring_soon']),
        Subscription.expires_at < now
    )

    for sub in expired:
        sub.status = 'expired'
        sub.save()

        try:
            await app.send_message(
                sub.user.telegram_id,
                "❌ <b>Подписка истекла</b>\n\n"
                "Ваша подписка закончилась. Прогнозы приостановлены.\n\n"
                "Продлите подписку, чтобы продолжить пользоваться всеми возможностями бота."
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления об истечении: {e}")

    logger.info(f"Проверка подписок завершена. Истекающих: {expiring_3d.count()}, Истёкших: {expired.count()}")


import time

# TTL для FSM состояний в секундах (1 час)
FSM_STATE_TTL = 3600


def cleanup_state_dict(state_dict: dict, ttl_seconds: int = FSM_STATE_TTL) -> int:
    """
    Очистка одного словаря состояний по TTL.
    Удаляет только записи старше ttl_seconds.
    Возвращает количество удалённых записей.
    """
    now = time.time()
    to_delete = []

    for user_id, state in state_dict.items():
        # Проверяем timestamp если есть
        created_at = state.get('created_at', 0) if isinstance(state, dict) else 0
        if now - created_at > ttl_seconds:
            to_delete.append(user_id)

    for user_id in to_delete:
        del state_dict[user_id]

    return len(to_delete)


async def cleanup_stale_fsm_states():
    """
    Очистка устаревших FSM состояний для предотвращения утечки памяти.
    Удаляет только состояния старше 1 часа (с timestamp).
    Вызывается каждый час.
    """
    try:
        from handlers.start import user_support_states
        from handlers.admin import admin_states
        from handlers.questions import user_question_states

        total_deleted = 0

        # Очищаем каждый словарь по отдельности
        total_deleted += cleanup_state_dict(user_support_states)
        total_deleted += cleanup_state_dict(admin_states)
        total_deleted += cleanup_state_dict(user_question_states)

        if total_deleted > 0:
            logger.info(f"Очищено {total_deleted} устаревших FSM состояний")
        else:
            # Логируем размер словарей для мониторинга
            total_size = len(user_support_states) + len(admin_states) + len(user_question_states)
            if total_size > 100:
                logger.warning(f"FSM словари содержат {total_size} активных состояний")

    except ImportError as e:
        logger.warning(f"Не удалось импортировать FSM состояния: {e}")
    except Exception as e:
        logger.error(f"Ошибка очистки FSM: {e}")


async def check_important_transits(app):
    """
    Проверка важных транзитов (точные аспекты на ближайшие 3 дня)
    Вызывается каждые 6 часов

    - Отправляет уведомления только с 10:00 до 21:00 по локальному времени пользователя
    - Исключает Луну и Солнце (только тяжёлые планеты)
    - Показывает только будущие транзиты (не прошедшие)
    - Исключает ночные транзиты (00:00 - 06:00)
    """
    from database.models import User
    from services.astro_engine import calculate_transits, calculate_local_natal
    from services.geocoder import get_timezone_offset
    import pytz

    logger.info("Проверка важных транзитов (тяжёлые планеты)...")

    # Планеты для исключения из уведомлений
    EXCLUDE_PLANETS = {'Луна', 'Солнце'}

    # Время отправки уведомлений (локальное время пользователя)
    NOTIFY_START_HOUR = 10  # с 10:00
    NOTIFY_END_HOUR = 21    # до 21:00

    # Время транзитов — исключаем ночные (00:00 - 06:00)
    TRANSIT_START_HOUR = 6  # не показывать транзиты раньше 06:00

    # Пользователи с включёнными уведомлениями
    users = User.select().where(
        User.natal_data_complete == True,
        User.push_transits == True,
        User.is_active == True
    )

    for user in users:
        if not user.has_active_subscription():
            continue

        try:
            # Определяем локальное время пользователя
            tz_name = user.residence_tz or user.birth_tz or "Europe/Moscow"
            try:
                tz = pytz.timezone(tz_name)
                user_now = datetime.now(tz)
                user_hour = user_now.hour
            except Exception:
                # Fallback: MSK (UTC+3)
                user_now = datetime.utcnow() + timedelta(hours=3)
                user_hour = user_now.hour

            # Проверяем, что сейчас подходящее время для уведомлений (10:00 - 21:00)
            if not (NOTIFY_START_HOUR <= user_hour < NOTIFY_END_HOUR):
                continue

            # Часовые пояса для расчётов
            birth_tz_hours = get_timezone_offset(user.birth_tz or "Europe/Moscow", user.birth_date)
            display_tz_hours = get_timezone_offset(tz_name, date.today())

            # Рассчитываем натальную карту
            natal = calculate_local_natal(
                birth_date=user.birth_date,
                birth_time=user.birth_time,
                birth_lat=user.birth_lat,
                birth_lon=user.birth_lon,
                residence_lat=user.residence_lat or user.birth_lat,
                residence_lon=user.residence_lon or user.birth_lon,
                timezone_hours=birth_tz_hours
            )

            # Рассчитываем транзиты на 3 дня вперёд
            today = date.today()
            transits = calculate_transits(
                natal_data=natal,
                start_date=today,
                days=3,
                residence_lat=user.residence_lat or user.birth_lat,
                residence_lon=user.residence_lon or user.birth_lon,
                timezone_hours=display_tz_hours,
                transit_cusps_tz=display_tz_hours
            )

            # Фильтруем:
            # 1. Только тяжёлые планеты (исключаем Луну и Солнце)
            # 2. Только будущие транзиты (exact_datetime > сейчас)
            # 3. Исключаем ночные транзиты (00:00 - 06:00)
            now_naive = user_now.replace(tzinfo=None)
            heavy_transits = [
                t for t in transits
                if t.get('transit_planet') not in EXCLUDE_PLANETS
                and t.get('exact_datetime') and t.get('exact_datetime') > now_naive
                and t.get('exact_datetime').hour >= TRANSIT_START_HOUR  # исключаем ночные
            ]

            if not heavy_transits:
                continue

            # Берём ближайшие 3 транзита
            upcoming = heavy_transits[:3]

            # Форматируем текст
            aspect_lines = []
            for t in upcoming:
                exact_dt = t.get('exact_datetime')
                date_str = exact_dt.strftime("%d.%m %H:%M") if exact_dt else "скоро"

                transit_sym = t.get('transit_symbol', '')
                transit_name = t.get('transit_planet', '')
                aspect_sym = t.get('aspect_symbol', '')
                aspect_name = t.get('aspect_name', '')
                natal_sym = t.get('natal_symbol', '')
                natal_name = t.get('natal_planet', '')

                line = f"• {transit_sym} {transit_name} {aspect_name} ({aspect_sym}) {natal_sym} {natal_name}"
                line += f"\n   📅 <b>{date_str}</b>"
                aspect_lines.append(line)

            aspect_text = "\n".join(aspect_lines)

            await app.send_message(
                user.telegram_id,
                f"🔔 <b>Важные транзиты на ближайшие дни</b>\n\n"
                f"{aspect_text}\n\n"
                f"💡 Откройте прогноз на указанные даты для подробностей.",
                reply_markup=None
            )
            logger.info(f"Уведомление о транзитах: {user.telegram_id}, аспектов: {len(upcoming)}")

        except Exception as e:
            logger.error(f"Ошибка проверки транзитов для {user.telegram_id}: {e}")


async def send_marketing_consent_requests(app):
    """
    Отправить запросы на согласие на рассылку (152-ФЗ, 38-ФЗ).

    Логика:
    - 1-я попытка: +30 минут после /start
    - 2-я попытка: +3 дня после 1-го отказа
    - 3-я попытка: +2 недели после 2-го отказа
    - После 3-го отказа: marketing_consent=False, больше не спрашиваем

    Вызывается каждый час.
    """
    from database.models import User
    from utils.keyboards import get_marketing_consent_keyboard
    from services.consent_service import (
        get_users_for_marketing_request, mark_marketing_asked,
        mark_bot_blocked
    )

    logger.info("Проверка маркетинговых запросов...")

    sent_count = 0
    blocked_count = 0

    users = get_users_for_marketing_request()

    for user in users:
        attempt = user.marketing_asked_count + 1

        try:
            # Текст зависит от номера попытки
            if attempt == 1:
                text = (
                    "⭐ <b>Подпишитесь на новости!</b>\n\n"
                    "Бесплатные функции, акции и новые возможности — "
                    "узнавайте первыми!\n\n"
                    "Вы можете отписаться в любой момент через "
                    "Настройки → Документы."
                )
            elif attempt == 2:
                text = (
                    "📬 <b>Ещё раз предлагаем подписаться!</b>\n\n"
                    "Подписчики первыми узнают об акциях и скидках.\n\n"
                    "Всего пара кликов, и вы в курсе всех новостей!"
                )
            else:  # attempt == 3
                text = (
                    "🔔 <b>Последнее предложение!</b>\n\n"
                    "Это последний раз, когда мы предлагаем подписаться на рассылку.\n\n"
                    "Больше не будем беспокоить, обещаем! 🙂"
                )

            await app.send_message(
                user.telegram_id,
                text,
                reply_markup=get_marketing_consent_keyboard()
            )

            # Отмечаем что показали запрос
            mark_marketing_asked(user)
            sent_count += 1

            logger.info(
                f"Отправлен маркетинговый запрос #{attempt} пользователю {user.telegram_id}"
            )

            # Небольшая задержка между отправками
            await asyncio.sleep(0.1)

        except Exception as e:
            error_str = str(e).lower()
            # Проверяем на блокировку бота
            if "blocked" in error_str or "deactivated" in error_str or "403" in error_str:
                mark_bot_blocked(user)
                blocked_count += 1
                logger.info(f"Пользователь {user.telegram_id} заблокировал бота")
            else:
                logger.error(f"Ошибка отправки маркетинга {user.telegram_id}: {e}")

    if sent_count > 0:
        logger.info(f"Отправлено {sent_count} маркетинговых запросов")
    if blocked_count > 0:
        logger.info(f"Обнаружено {blocked_count} заблокировавших бота")


def run_async(coro):
    """Обёртка для запуска async функции из синхронного контекста BackgroundScheduler"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Ошибка выполнения async задачи: {e}")


def setup_jobs(app, send_forecast_func: Callable):
    """
    Настройка всех задач планировщика

    Args:
        app: Pyrogram клиент
        send_forecast_func: Функция отправки прогноза
    """
    global scheduler

    if scheduler is None:
        scheduler = init_scheduler()

    # Обёртки для async функций
    def check_forecast_time_sync():
        run_async(check_forecast_time(app, send_forecast_func))

    def check_subscriptions_sync():
        run_async(check_subscriptions(app))

    def check_important_transits_sync():
        run_async(check_important_transits(app))

    def cleanup_stale_fsm_states_sync():
        run_async(cleanup_stale_fsm_states())

    def send_marketing_consent_sync():
        run_async(send_marketing_consent_requests(app))

    # Проверка времени прогноза — каждую минуту
    scheduler.add_job(
        check_forecast_time_sync,
        CronTrigger(minute='*'),
        id='check_forecast_time',
        replace_existing=True,
        name='Проверка времени прогноза'
    )

    # Проверка подписок — ежедневно в 10:00
    scheduler.add_job(
        check_subscriptions_sync,
        CronTrigger(hour=10, minute=0),
        id='check_subscriptions',
        replace_existing=True,
        name='Проверка подписок'
    )

    # Проверка важных транзитов — каждые 6 часов
    scheduler.add_job(
        check_important_transits_sync,
        IntervalTrigger(hours=6),
        id='check_transits',
        replace_existing=True,
        name='Проверка транзитов'
    )

    # Очистка устаревших FSM состояний — каждый час
    scheduler.add_job(
        cleanup_stale_fsm_states_sync,
        IntervalTrigger(hours=1),
        id='cleanup_fsm',
        replace_existing=True,
        name='Очистка FSM состояний'
    )

    # Отправка маркетинговых запросов — каждый час (152-ФЗ, 38-ФЗ)
    scheduler.add_job(
        send_marketing_consent_sync,
        IntervalTrigger(hours=1),
        id='marketing_consent',
        replace_existing=True,
        name='Запросы маркетингового согласия'
    )

    logger.info("Задачи планировщика настроены")


def get_scheduler_status() -> dict:
    """Получить статус планировщика"""
    global scheduler

    if scheduler is None:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None
        })

    return {
        "running": scheduler.running,
        "jobs": jobs
    }
