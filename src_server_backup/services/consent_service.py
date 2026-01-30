#!/usr/bin/env python3
# coding: utf-8

"""
Сервис управления согласиями (152-ФЗ, 38-ФЗ)

Функционал:
- Согласие на обработку ПД (обязательное)
- Согласие на рассылку (опциональное, до 3 запросов)
- Журнал действий с согласиями
- Удаление данных пользователя
"""

import json
import logging
from datetime import datetime, timedelta

from database.models import (
    User, ConsentLog, Subscription, Forecast,
    Conversation, CalendarCache, SupportTicket
)

logger = logging.getLogger(__name__)

# Константы для планирования маркетинговых запросов
MARKETING_DELAYS = {
    1: timedelta(minutes=30),    # Первый запрос через 30 минут после /start
    2: timedelta(days=3),        # Второй через 3 дня после отказа
    3: timedelta(weeks=2),       # Третий через 2 недели после отказа
}


def log_consent_action(user: User, action: str, details: dict = None):
    """
    Запись действия в журнал согласий

    Типы действий:
    - pd_granted: дал согласие на ПД
    - pd_revoked: отозвал согласие на ПД
    - marketing_granted: подписался на рассылку
    - marketing_revoked: отписался от рассылки
    - marketing_asked: показали запрос на рассылку
    - marketing_declined: отказался от рассылки (кнопка "Не сейчас")
    - user_blocked: заблокировал бота
    - user_unblocked: разблокировал бота (новый /start)
    - data_deleted: удалил свои данные
    """
    ConsentLog.create(
        user=user,
        action=action,
        details=json.dumps(details, ensure_ascii=False) if details else None
    )
    logger.info(f"ConsentLog: user={user.telegram_id}, action={action}")


def grant_pd_consent(user: User) -> bool:
    """
    Дать согласие на обработку ПД

    Вызывается при нажатии кнопки "Принимаю" на экране согласия.
    """
    user.pd_consent = True
    user.pd_consent_at = datetime.now()
    user.is_bot_blocked = False
    user.bot_blocked_at = None
    user.save()

    log_consent_action(user, "pd_granted", {
        "ip": None,  # Telegram не даёт IP
        "timestamp": datetime.now().isoformat()
    })

    # Планируем первый запрос на рассылку
    schedule_marketing_request(user)

    return True


def revoke_pd_consent(user: User) -> bool:
    """
    Отозвать согласие на обработку ПД

    После отзыва пользователь блокируется,
    но запись в БД НЕ удаляется (для истории).
    При следующем /start потребуется повторное согласие.
    """
    user.pd_consent = False
    user.pd_consent_at = None
    user.is_bot_blocked = True
    user.bot_blocked_at = datetime.now()

    # Сбрасываем маркетинговое согласие
    user.marketing_consent = None
    user.marketing_consent_at = None
    user.marketing_asked_count = 0
    user.marketing_next_ask_at = None

    user.save()

    log_consent_action(user, "pd_revoked", {
        "timestamp": datetime.now().isoformat()
    })

    return True


def grant_marketing_consent(user: User) -> bool:
    """
    Дать согласие на рассылку

    Вызывается при нажатии кнопки "Подписаться".
    """
    user.marketing_consent = True
    user.marketing_consent_at = datetime.now()
    user.marketing_next_ask_at = None  # Больше не спрашиваем
    user.save()

    log_consent_action(user, "marketing_granted", {
        "asked_count": user.marketing_asked_count,
        "timestamp": datetime.now().isoformat()
    })

    return True


def refuse_marketing_consent(user: User, final: bool = False) -> bool:
    """
    Отказаться от рассылки

    final=False (кнопка "Не сейчас"): планируем следующий запрос
    final=True (после 3-го отказа или настройки): больше не спрашиваем

    После 3-го отказа marketing_consent = False (финальный отказ).
    """
    user.marketing_asked_count += 1

    if final or user.marketing_asked_count >= 3:
        # Финальный отказ
        user.marketing_consent = False
        user.marketing_consent_at = datetime.now()
        user.marketing_next_ask_at = None
        action = "marketing_revoked"
    else:
        # Отложенный отказ - планируем следующий запрос
        user.marketing_consent = None  # Всё ещё "не решил"
        schedule_marketing_request(user)
        action = "marketing_declined"

    user.save()

    log_consent_action(user, action, {
        "asked_count": user.marketing_asked_count,
        "final": final or user.marketing_asked_count >= 3,
        "timestamp": datetime.now().isoformat()
    })

    return True


def revoke_marketing_consent(user: User) -> bool:
    """
    Отписаться от рассылки (из настроек)

    Пользователь сам отключает рассылку.
    marketing_consent = False, больше не спрашиваем.
    """
    user.marketing_consent = False
    user.marketing_consent_at = datetime.now()
    user.marketing_next_ask_at = None
    user.save()

    log_consent_action(user, "marketing_revoked", {
        "source": "settings",
        "timestamp": datetime.now().isoformat()
    })

    return True


def schedule_marketing_request(user: User):
    """
    Запланировать следующий запрос на рассылку

    Расписание:
    - 1-я попытка: +30 минут после /start
    - 2-я попытка: +3 дня после 1-го отказа
    - 3-я попытка: +2 недели после 2-го отказа
    """
    next_ask = user.marketing_asked_count + 1

    if next_ask > 3:
        # Больше не спрашиваем
        user.marketing_next_ask_at = None
    else:
        delay = MARKETING_DELAYS.get(next_ask, timedelta(days=1))
        user.marketing_next_ask_at = datetime.now() + delay

    user.save()
    logger.info(f"Marketing request scheduled: user={user.telegram_id}, attempt={next_ask}, at={user.marketing_next_ask_at}")


def mark_marketing_asked(user: User):
    """
    Отметить что запрос на рассылку был показан

    Вызывается планировщиком при отправке сообщения.
    Сбрасывает marketing_next_ask_at чтобы избежать повторной отправки.
    Счётчик НЕ увеличивается здесь — он увеличивается в refuse_marketing_consent()
    когда пользователь нажимает кнопку "Не сейчас".
    """
    # Сбрасываем время следующего запроса, чтобы не отправлять повторно
    # Если пользователь не ответит, следующий запрос будет запланирован
    # только когда он нажмёт "Не сейчас" (в refuse_marketing_consent)
    user.marketing_next_ask_at = None
    user.save()

    log_consent_action(user, "marketing_asked", {
        "asked_count": user.marketing_asked_count + 1,
        "timestamp": datetime.now().isoformat()
    })


def mark_bot_blocked(user: User):
    """
    Отметить что пользователь заблокировал бота

    Вызывается при получении ошибки 403 при отправке сообщения.
    """
    user.is_bot_blocked = True
    user.bot_blocked_at = datetime.now()
    user.save()

    log_consent_action(user, "user_blocked", {
        "timestamp": datetime.now().isoformat()
    })


def mark_bot_unblocked(user: User):
    """
    Отметить что пользователь разблокировал бота

    Вызывается при получении /start от заблокированного пользователя.
    """
    was_blocked = user.is_bot_blocked
    user.is_bot_blocked = False
    user.bot_blocked_at = None
    user.save()

    if was_blocked:
        log_consent_action(user, "user_unblocked", {
            "timestamp": datetime.now().isoformat()
        })


def delete_user_data(user: User) -> bool:
    """
    Полное удаление данных пользователя

    Удаляет:
    - История прогнозов
    - Разговоры с AI
    - Кэш календаря
    - Тикеты поддержки
    - Подписки

    НЕ удаляет:
    - Саму запись User (для истории согласий)
    - ConsentLog (доказательство)

    После удаления is_bot_blocked = True.
    """
    # Удаляем связанные данные
    Forecast.delete().where(Forecast.user == user).execute()
    Conversation.delete().where(Conversation.user == user).execute()
    CalendarCache.delete().where(CalendarCache.user == user).execute()
    SupportTicket.delete().where(SupportTicket.user == user).execute()
    Subscription.delete().where(Subscription.user == user).execute()

    # Очищаем персональные данные в User
    user.username = None
    user.first_name = ""

    # Очищаем натальные данные
    user.birth_date = None
    user.birth_time = None
    user.birth_place = None
    user.birth_lat = None
    user.birth_lon = None
    user.birth_tz = None

    # Очищаем место проживания
    user.residence_place = None
    user.residence_lat = None
    user.residence_lon = None

    # Сбрасываем настройки
    user.natal_data_complete = False
    user.questions_today = 0
    user.questions_reset_date = None

    # Сбрасываем согласия
    user.pd_consent = False
    user.pd_consent_at = None
    user.marketing_consent = None
    user.marketing_consent_at = None
    user.marketing_asked_count = 0
    user.marketing_next_ask_at = None

    # Блокируем
    user.is_bot_blocked = True
    user.bot_blocked_at = datetime.now()

    user.save()

    log_consent_action(user, "data_deleted", {
        "timestamp": datetime.now().isoformat()
    })

    logger.info(f"User data deleted: telegram_id={user.telegram_id}")
    return True


def has_pd_consent(user: User) -> bool:
    """Проверить есть ли согласие на ПД"""
    return user.pd_consent is True


def has_marketing_consent(user: User) -> bool:
    """Проверить есть ли согласие на рассылку"""
    return user.marketing_consent is True


def can_send_marketing(user: User) -> bool:
    """Можно ли отправлять рассылку пользователю"""
    return (
        user.pd_consent is True and
        user.marketing_consent is True and
        user.is_bot_blocked is False
    )


def should_ask_marketing(user: User) -> bool:
    """Нужно ли спросить о рассылке"""
    if user.marketing_consent is not None:
        # Уже решил (True или False)
        return False

    if user.marketing_asked_count >= 3:
        # Спрашивали 3 раза
        return False

    if user.marketing_next_ask_at is None:
        return False

    return user.marketing_next_ask_at <= datetime.now()


def get_users_for_marketing_request():
    """
    Получить пользователей для запроса на рассылку

    Критерии:
    - pd_consent = True
    - marketing_consent IS NULL (не решил)
    - marketing_next_ask_at <= now
    - marketing_asked_count < 3
    - is_bot_blocked = False
    """
    now = datetime.now()
    return User.select().where(
        (User.pd_consent == True) &
        (User.marketing_consent.is_null()) &
        (User.marketing_next_ask_at <= now) &
        (User.marketing_asked_count < 3) &
        (User.is_bot_blocked == False)
    )


def get_users_for_broadcast():
    """
    Получить пользователей для админской рассылки

    Критерии:
    - pd_consent = True
    - marketing_consent = True
    - is_bot_blocked = False
    """
    return User.select().where(
        (User.pd_consent == True) &
        (User.marketing_consent == True) &
        (User.is_bot_blocked == False)
    )


def get_consent_statistics() -> dict:
    """
    Получить статистику согласий
    """
    total = User.select().count()
    pd_consented = User.select().where(User.pd_consent == True).count()
    marketing_consented = User.select().where(User.marketing_consent == True).count()
    marketing_refused = User.select().where(User.marketing_consent == False).count()
    marketing_pending = User.select().where(User.marketing_consent.is_null()).count()
    blocked = User.select().where(User.is_bot_blocked == True).count()

    return {
        "total_users": total,
        "pd_consented": pd_consented,
        "pd_not_consented": total - pd_consented,
        "marketing_consented": marketing_consented,
        "marketing_refused": marketing_refused,
        "marketing_pending": marketing_pending,
        "blocked_users": blocked
    }
