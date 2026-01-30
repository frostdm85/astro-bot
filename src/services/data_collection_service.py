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
    Уведомить админа об оплате подписки

    Args:
        client: Pyrogram Client
        user: User модель
    """
    try:
        # Проверяем, заполнил ли пользователь данные
        data_status = "✅ Данные заполнены" if user.user_data_submitted else "❌ Данные не заполнены"

        # Формируем сообщение с краткой информацией
        data_preview = ""
        if user.user_data_submitted:
            data_preview = f"""
📅 Дата рождения: {user.birth_date.strftime('%d.%m.%Y') if user.birth_date else '—'}
⏰ Время: {user.birth_time.strftime('%H:%M') if user.birth_time else '—'}
📍 Город рождения: {user.birth_place or '—'}
🏠 Город проживания: {user.residence_place or '—'}"""

        message = f"""💳 <b>Новая оплата подписки!</b>

👤 <b>Пользователь:</b>
• ID: <code>{user.telegram_id}</code>
• Username: @{user.username or 'нет'}
• Имя: {user.first_name}

📝 <b>Статус данных:</b> {data_status}{data_preview}

✅ <b>Подписка активирована!</b>"""

        await client.send_message(ADMIN_ID, message)
        logger.info(f"Админ уведомлён об оплате от пользователя {user.telegram_id}")

    except Exception as e:
        logger.error(f"Ошибка уведомления админа об оплате: {e}")
