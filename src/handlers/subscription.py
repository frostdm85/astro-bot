#!/usr/bin/env python3
# coding: utf-8

"""
Обработчик подписки
- Информация о подписке
- Оплата (YooKassa)
"""

import logging

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import SUBSCRIPTION_PRICE, ADMIN_USERNAME
from database.models import User
from services.data_collection_service import notify_admin_payment

logger = logging.getLogger(__name__)


# ============== ТЕКСТЫ ==============

SUBSCRIPTION_INFO_TEXT = """🔮 <b>Персональные прогнозы</b>

Для получения персональных астрологических прогнозов:

1️⃣ <b>Оплатите подписку</b> (1990₽ на 30 дней)
2️⃣ <b>Заполните данные</b> (дата/время/место рождения)
3️⃣ <b>Ожидайте обработки</b> данных астрологом

━━━━━━━━━━━━━━━━━━━

💰 <b>Стоимость:</b> {price}₽ на 30 дней

<b>Что входит:</b>
✅ Ежедневные персональные прогнозы
✅ Прогнозы на любой период
✅ 10 вопросов AI-астрологу в день
✅ Голосовые ответы
✅ Уведомления о транзитах"""

PAYMENT_TEXT = """💳 <b>Оформление подписки</b>

━━━━━━━━━━━━━━━━━━━
📦 <b>Подписка на 1 месяц</b>

✅ Ежедневные персональные прогнозы
✅ Прогнозы на любой период
✅ 10 вопросов AI-астрологу в день
✅ Голосовые ответы
✅ Уведомления о транзитах

💰 Стоимость: <b>{price} ₽</b>

━━━━━━━━━━━━━━━━━━━
⚠️ <i>Оплата временно недоступна.
Свяжитесь с администратором для активации подписки.</i>"""


# ============== ОБРАБОТЧИКИ ==============

async def handle_subscription_info(callback: CallbackQuery):
    """Показать информацию о подписке"""
    await callback.answer()

    await callback.message.edit_text(
        SUBSCRIPTION_INFO_TEXT.format(price=SUBSCRIPTION_PRICE),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Оплатить", callback_data="subscription:pay")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
        ])
    )


async def handle_subscription_pay(callback: CallbackQuery):
    """Переход к оплате (пока заглушка)"""
    await callback.answer()

    # Пока YooKassa не настроена — показываем заглушку
    await callback.message.edit_text(
        PAYMENT_TEXT.format(price=SUBSCRIPTION_PRICE),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"👨‍💻 Связаться с {ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="subscription:info")]
        ])
    )


def register_handlers(app: Client):
    """Регистрация обработчиков"""
    from pyrogram.handlers import CallbackQueryHandler
    from pyrogram import filters

    logger.info("Регистрация обработчиков subscription.py...")

    subscription_callback_filter = filters.regex(r"^(subscription:info|subscription:pay)$")

    async def subscription_callback_router(client: Client, callback: CallbackQuery):
        """Роутер callback-кнопок подписки"""
        data = callback.data

        if data == "subscription:info":
            await handle_subscription_info(callback)
        elif data == "subscription:pay":
            await handle_subscription_pay(callback)

    app.add_handler(CallbackQueryHandler(subscription_callback_router, subscription_callback_filter))

    logger.info("Обработчики subscription.py зарегистрированы")
