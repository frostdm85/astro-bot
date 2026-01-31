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

from config import SUBSCRIPTION_PRICE, ADMIN_USERNAME, SUBSCRIPTION_PLANS
from database.models import User, Subscription
from services.data_collection_service import notify_admin_payment
from services import yookassa_service

logger = logging.getLogger(__name__)


# ============== ТЕКСТЫ ==============

SUBSCRIPTION_INFO_TEXT = """🔮 <b>Персональные прогнозы</b>

Для получения персональных астрологических прогнозов:

1️⃣ <b>Оплатите подписку</b> (от 1990₽ на 30 дней)
2️⃣ <b>Заполните данные</b> (дата/время/место рождения)
3️⃣ <b>Ожидайте обработки</b> данных астрологом

━━━━━━━━━━━━━━━━━━━

<b>Что входит:</b>
✅ Ежедневные персональные прогнозы
✅ 10 вопросов AI-астрологу в день
✅ Голосовые ответы
✅ Уведомления о транзитах"""

TARIFF_SELECTION_TEXT = """💳 <b>Выберите тариф подписки</b>

━━━━━━━━━━━━━━━━━━━

<b>Что входит во все тарифы:</b>
✅ Ежедневные персональные прогнозы
✅ 10 вопросов AI-астрологу в день
✅ Голосовые ответы
✅ Уведомления о транзитах

━━━━━━━━━━━━━━━━━━━

Выберите период подписки:"""

PAYMENT_CREATED_TEXT = """💳 <b>Ссылка на оплату создана</b>

━━━━━━━━━━━━━━━━━━━
📦 Подписка: <b>{label}</b>
💰 Сумма: <b>{amount} ₽</b>
⏱️ Период: <b>{days} дней</b>

━━━━━━━━━━━━━━━━━━━

Нажмите на кнопку ниже для перехода к оплате.

⚠️ После успешной оплаты подписка активируется автоматически."""

PAYMENT_ERROR_TEXT = """❌ <b>Ошибка создания платежа</b>

Произошла ошибка при создании ссылки на оплату.

Попробуйте ещё раз или свяжитесь с администратором: {admin}"""


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
    """Показать выбор тарифов"""
    await callback.answer()

    # Проверяем настройку YooKassa
    if not yookassa_service.is_configured():
        await callback.message.edit_text(
            PAYMENT_ERROR_TEXT.format(admin=ADMIN_USERNAME),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"👨‍💻 Связаться с {ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="subscription:info")]
            ])
        )
        return

    # Кнопки тарифов
    keyboard = []
    for plan_id, plan_data in SUBSCRIPTION_PLANS.items():
        emoji = plan_data["emoji"]
        label = plan_data["label"]
        price = plan_data["price"]
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {label} — {price}₽",
                callback_data=f"subscription:plan:{plan_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="subscription:info")])

    await callback.message.edit_text(
        TARIFF_SELECTION_TEXT,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_plan_selection(callback: CallbackQuery, plan_id: str):
    """Обработка выбора тарифа и создание платежа"""
    await callback.answer()

    # Получаем данные тарифа
    plan_data = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan_data:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return

    user_id = callback.from_user.id
    amount = plan_data["price"]
    days = plan_data["days"]
    label = plan_data["label"]

    # Создаём платёж в YooKassa
    payment_info = yookassa_service.create_payment(
        user_id=user_id,
        amount=amount,
        description=f"Подписка Астро-бот на {label.lower()}"
    )

    if not payment_info:
        await callback.message.edit_text(
            PAYMENT_ERROR_TEXT.format(admin=ADMIN_USERNAME),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"👨‍💻 Связаться с {ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME}")],
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="subscription:pay")],
                [InlineKeyboardButton("◀️ Назад", callback_data="subscription:info")]
            ])
        )
        return

    # Сохраняем информацию о платеже в БД
    try:
        user = User.get(User.telegram_id == user_id)

        # Создаём или обновляем запись подписки
        subscription, created = Subscription.get_or_create(
            user=user,
            defaults={
                "payment_id": payment_info["payment_id"],
                "amount": amount,
                "plan": plan_id,
                "is_active": False
            }
        )

        if not created:
            subscription.payment_id = payment_info["payment_id"]
            subscription.amount = amount
            subscription.plan = plan_id
            subscription.is_active = False
            subscription.save()

        logger.info(f"Создан платёж {payment_info['payment_id']} для user {user_id}, тариф {plan_id}")

    except Exception as e:
        logger.error(f"Ошибка сохранения подписки для user {user_id}: {e}")

    # Показываем ссылку на оплату
    await callback.message.edit_text(
        PAYMENT_CREATED_TEXT.format(
            label=label,
            amount=amount,
            days=days
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Перейти к оплате", url=payment_info["confirmation_url"])],
            [InlineKeyboardButton("◀️ Назад", callback_data="subscription:pay")]
        ])
    )


def register_handlers(app: Client):
    """Регистрация обработчиков"""
    from pyrogram.handlers import CallbackQueryHandler
    from pyrogram import filters

    logger.info("Регистрация обработчиков subscription.py...")

    subscription_callback_filter = filters.regex(r"^subscription:(info|pay|plan:.+)$")

    async def subscription_callback_router(client: Client, callback: CallbackQuery):
        """Роутер callback-кнопок подписки"""
        data = callback.data

        if data == "subscription:info":
            await handle_subscription_info(callback)
        elif data == "subscription:pay":
            await handle_subscription_pay(callback)
        elif data.startswith("subscription:plan:"):
            plan_id = data.replace("subscription:plan:", "")
            await handle_plan_selection(callback, plan_id)

    app.add_handler(CallbackQueryHandler(subscription_callback_router, subscription_callback_filter))

    logger.info("Обработчики subscription.py зарегистрированы")
