#!/usr/bin/env python3
# coding: utf-8

"""
Сервис сбора данных от пользователей
- Уведомления админа о заполненных данных
- Уведомления админа об оплате
"""

import logging
from datetime import datetime

from pyrogram import Client
from config import ADMIN_ID
from database.models import User

logger = logging.getLogger(__name__)


async def notify_admin_data_submitted(client: Client, user: User, has_paid: bool = False):
    """
    Уведомить админа о заполнении данных пользователем

    Args:
        client: Pyrogram Client
        user: User модель
        has_paid: Есть ли активная подписка
    """
    try:
        # Формируем статус оплаты
        payment_status = "✅ Оплачено" if has_paid else "❌ Не оплачено"

        # Форматируем данные брака
        marriage_info = ""
        if user.marriage_date or user.marriage_city:
            marriage_info = f"\n\n💍 <b>Брак:</b>"
            if user.marriage_date:
                marriage_info += f"\n• Дата: {user.marriage_date.strftime('%d.%m.%Y')}"
            if user.marriage_city:
                marriage_info += f"\n• Город: {user.marriage_city}"
        else:
            marriage_info = "\n\n💍 <b>Брак:</b> Данные не указаны"

        message = f"""📝 <b>Новый пользователь заполнил данные</b>

👤 <b>Пользователь:</b>
• ID: <code>{user.telegram_id}</code>
• Username: @{user.username or 'нет'}
• Имя: {user.first_name}

📅 <b>Данные рождения:</b>
• Дата: {user.birth_date.strftime('%d.%m.%Y') if user.birth_date else 'Не указана'}
• Время: {user.birth_time.strftime('%H:%M') if user.birth_time else 'Не указано'}
• Город: {user.birth_place or 'Не указан'}

🏠 <b>Текущий город:</b> {user.residence_place or 'Не указан'}{marriage_info}

💳 <b>Статус оплаты:</b> {payment_status}

🕐 <b>Заполнено:</b> {user.user_data_submitted_at.strftime('%d.%m.%Y %H:%M')}"""

        await client.send_message(ADMIN_ID, message)
        logger.info(f"Админ уведомлён о данных пользователя {user.telegram_id}")

    except Exception as e:
        logger.error(f"Ошибка уведомления админа о данных: {e}")


async def notify_admin_payment(client: Client, user: User):
    """
    Уведомить админа об оплате подписки с ПОЛНОЙ анкетой

    Args:
        client: Pyrogram Client
        user: User модель
    """
    try:
        # Получаем активную подписку
        subscription = user.get_subscription()

        # Формируем сообщение
        message = f"📝 Новый пользователь оплатил подписку\n\n"
        message += f"👤 Пользователь:\n"
        message += f"• ID: {user.telegram_id}\n"
        message += f"• Username: @{user.username}\n" if user.username else ""
        message += f"• Имя: {user.first_name}\n\n"

        # Данные рождения
        if user.birth_date or user.birth_time or user.birth_place:
            message += f"📅 Данные рождения:\n"
            message += f"• Дата: {user.birth_date.strftime('%d.%m.%Y') if user.birth_date else '—'}\n"
            message += f"• Время: {user.birth_time.strftime('%H:%M') if user.birth_time else '—'}\n"
            message += f"• Город: {user.birth_place or '—'}\n\n"

        # Текущий город
        if user.residence_place:
            message += f"🏠 Текущий город: {user.residence_place}\n\n"

        # Брак
        if user.marriage_date or user.marriage_city:
            message += f"💍 Брак:\n"
            message += f"• Дата: {user.marriage_date.strftime('%d.%m.%Y') if user.marriage_date else '—'}\n"
            message += f"• Город: {user.marriage_city or '—'}\n\n"

        # Статус оплаты
        if subscription:
            plan_labels = {
                "1_month": "1 месяц",
                "3_months": "3 месяца",
                "6_months": "6 месяцев",
                "1_year": "1 год"
            }
            plan_label = plan_labels.get(subscription.plan, subscription.plan)
            message += f"💳 Статус оплаты: ✅ ОПЛАЧЕНО\n"
            message += f"• Тариф: {plan_label}\n"
            message += f"• Сумма: {subscription.amount} ₽\n"
            message += f"• Действует до: {subscription.expires_at.strftime('%d.%m.%Y') if subscription.expires_at else '—'}\n\n"

        # Время оплаты
        message += f"🕐 Оплачено: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"

        # Отправляем админу
        await client.send_message(ADMIN_ID, message)
        logger.info(f"Уведомление об оплате отправлено админу для пользователя {user.telegram_id}")

    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")
        raise
