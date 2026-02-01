#!/usr/bin/env python3
# coding: utf-8

"""
Обработчик /start и главное меню
"""

import logging
import asyncio
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID, ADMIN_USERNAME, SUBSCRIPTION_PRICE
from database.models import get_or_create_user, User, Subscription, SupportTicket, SupportMessage
from utils.keyboards import (
    get_welcome_keyboard,
    get_no_subscription_keyboard,
    get_main_menu_keyboard,
    get_after_payment_keyboard,
    get_help_keyboard,
    get_period_keyboard,
    get_calendar_keyboard,
    get_support_keyboard,
    get_payment_keyboard,
    get_payment_pending_keyboard
)
from config import WEBAPP_URL
from services import yookassa_service
from services.data_collection_service import notify_admin_payment
from handlers.forecast import (
    handle_forecast_today,
    handle_forecast_period,
    handle_forecast_date,
    handle_voice_forecast
)
from handlers.questions import (
    handle_ask_question,
    handle_ask_about_forecast,
    handle_voice_answer
)

logger = logging.getLogger(__name__)

# FSM состояния для поддержки
user_support_states = {}  # {user_id: {"state": "waiting_message"}}


import time as time_module

def set_support_state(user_id: int, state: str):
    """Установить состояние поддержки с timestamp для TTL"""
    user_support_states[user_id] = {
        "state": state,
        "created_at": time_module.time()
    }


def get_support_state(user_id: int) -> dict:
    """Получить состояние"""
    return user_support_states.get(user_id, {"state": None})


def clear_support_state(user_id: int):
    """Очистить состояние"""
    if user_id in user_support_states:
        del user_support_states[user_id]


def parse_callback_int(data: str, prefix: str, delimiter: str = ":") -> int:
    """
    Безопасный парсинг целого числа из callback data.

    Args:
        data: Полная строка callback_data
        prefix: Префикс (например "ask_about_forecast:")
        delimiter: Разделитель (по умолчанию ":")

    Returns:
        Целое число или None при ошибке парсинга
    """
    try:
        suffix = data.replace(prefix, "")
        return int(suffix)
    except (ValueError, AttributeError):
        return None


# ============== ТЕКСТЫ ==============

WELCOME_NO_DATA_TEXT = """🌟 <b>Добро пожаловать в Астро-прогноз!</b>

Я — ваш персональный астрологический помощник.

📋 <b>Что я умею:</b>
• 🔮 Ежедневные прогнозы на основе транзитов
• 📅 Прогнозы на любой период
• 💬 Отвечаю на вопросы об астрологии
• 🎤 Понимаю голосовые сообщения

⏳ <b>Ваш профиль ещё не настроен</b>"""

WELCOME_NO_SUB_TEXT = """🌟 <b>Астро-прогноз</b>

Здравствуйте, <b>{name}</b>!

📅 Дата рождения: {birth_date}
📍 Место рождения: {birth_place}
🏠 Проживание: {residence}

❌ <b>Подписка неактивна</b>

Для получения персональных прогнозов оформите подписку.

💰 Стоимость: {price} ₽/месяц

<i>Ваш астролог, Дмитрий Старков</i> ✨"""

MAIN_MENU_TEXT = """🌟 <b>Астро-прогноз</b>

Здравствуйте, <b>{name}</b>!

✅ Подписка активна до: <b>{expires}</b>

❓ Вопросов сегодня: {questions_used}/{questions_total}
⏰ Время прогноза: {forecast_time}

<i>Ваш астролог, Дмитрий Старков</i> ✨"""

HELP_TEXT = """ℹ️ <b>Справка</b>

━━
🔮 <b>Как работает бот?</b>

Бот использует методологию транзитного анализа для составления персональных прогнозов.

<b>Транзиты</b> — это текущие положения планет относительно вашей натальной карты. Они показывают актуальные энергии и тенденции в вашей жизни.

━━
📋 <b>Возможности бота:</b>

• 🔮 Ежедневный персональный прогноз
• 📅 Прогнозы на период (3 дня, неделя, месяц)
• 📆 Прогноз на конкретную дату
• 💬 До 10 вопросов AI-астрологу в день
• 🎤 Голосовые сообщения и ответы
• 🔔 Уведомления о важных транзитах"""

HELP_METHOD_TEXT = """📚 <b>Методология анализа</b>

━━
<b>Основные принципы:</b>

1️⃣ <b>Формулы планет</b> — каждая планета имеет набор ключевых значений, которые проявляются в зависимости от аспектов

2️⃣ <b>Транзитный анализ</b> — изучение текущих положений планет относительно натальной карты

3️⃣ <b>Орбисы аспектов</b> — точность аспекта влияет на силу его проявления

4️⃣ <b>Дома гороскопа</b> — сферы жизни, в которых проявляются планетные влияния

━━
Прогнозы бота учитывают все эти факторы для создания персонализированных рекомендаций."""

SETTINGS_TEXT = """⚙️ <b>Настройки</b>

━━
⏰ Время прогноза: <b>{forecast_time}</b>
   <i>Ежедневный прогноз приходит в это время</i>

🔔 Уведомления о транзитах: <b>{push_status}</b>
   <i>Пуш при точных аспектах (орбис 0-1°)</i>

━━
📊 <b>Ваши данные:</b>
📅 Дата рождения: {birth_date}
📍 Место рождения: {birth_place}
🏠 Проживание: {residence}

━━
💳 Подписка: {sub_status}"""

SUPPORT_TEXT = """👨‍💻 <b>Поддержка</b>

Если у вас есть вопросы или проблемы, напишите сообщение — администратор ответит в ближайшее время.

━━
Чтобы создать новое обращение, нажмите кнопку ниже."""

SUPPORT_NEW_TEXT = """✏️ <b>Новое обращение</b>

Опишите вашу проблему или вопрос. Администратор ответит в ближайшее время.

Отправьте текстовое сообщение."""

SUPPORT_SENT_TEXT = """✅ <b>Обращение отправлено!</b>

Ваше сообщение передано администратору.
Ожидайте ответа — вы получите уведомление."""

SUPPORT_LIST_TEXT = """📋 <b>Ваши обращения</b>

{tickets_list}"""

SUPPORT_NO_TICKETS_TEXT = """📭 <b>У вас нет обращений</b>

Нажмите "Новое обращение", чтобы связаться с поддержкой."""

PAYMENT_TEXT = """💳 <b>Оформление подписки</b>

━━
📦 <b>Подписка на 1 месяц</b>

✅ Ежедневные персональные прогнозы
✅ Прогнозы на любой период
✅ 10 вопросов AI-астрологу в день
✅ Голосовые ответы
✅ Уведомления о транзитах

💰 Стоимость: <b>{price} ₽</b>

━━
Нажмите кнопку для перехода к оплате.
После оплаты подписка активируется автоматически."""

PAYMENT_PENDING_TEXT = """⏳ <b>Ожидание оплаты</b>

Платёж создан. Перейдите по ссылке для завершения оплаты.

После оплаты нажмите кнопку "✅ Я оплатил" для проверки статуса."""

PAYMENT_SUCCESS_TEXT = """✅ <b>Подписка активирована!</b>

Спасибо за оплату! Теперь вам доступны все функции:

🔮 Ежедневные прогнозы
📅 Прогнозы на любой период
💬 Вопросы AI-астрологу

Приятного использования!"""

PAYMENT_NOT_FOUND_TEXT = """❌ <b>Платёж не найден</b>

Не найдено ожидающих оплаты платежей.
Создайте новый платёж."""

PAYMENT_STILL_PENDING_TEXT = """⏳ <b>Платёж ещё не оплачен</b>

Перейдите по ссылке и завершите оплату.
После оплаты нажмите "✅ Я оплатил" снова."""

PAYMENT_FAILED_TEXT = """❌ <b>Оплата не прошла</b>

Платёж был отменён или истёк.
Попробуйте создать новый платёж."""

PERIOD_TEXT = """📅 <b>Выберите период прогноза:</b>

Чем короче период, тем детальнее прогноз."""

CALENDAR_TEXT = """📆 <b>Выберите дату для прогноза:</b>

Используйте кнопки для навигации.
Можно выбрать дату до 30 дней вперёд."""

TIME_SELECTION_TEXT = """⏰ <b>Выберите время получения прогноза:</b>

Прогноз будет приходить каждый день в выбранное время по вашему часовому поясу ({timezone})."""


# ============== ХЕЛПЕРЫ ==============

def format_user_info(user: User) -> dict:
    """Форматирование данных пользователя"""
    from config import QUESTIONS_PER_DAY

    birth_date = user.birth_datetime_str if user.birth_date else "Не указано"
    birth_place = user.birth_place or "Не указано"
    residence = user.residence_place or "Не указано"

    sub = user.get_subscription()
    if sub and sub.status in ['active', 'expiring_soon']:
        expires = sub.expires_at.strftime("%d.%m.%Y") if sub.expires_at else "—"
        sub_status = f"✅ Активна до {expires}"
    else:
        expires = "—"
        sub_status = "❌ Неактивна"

    return {
        "name": user.display_name,
        "birth_date": birth_date,
        "birth_place": birth_place,
        "residence": residence,
        "expires": expires,
        "sub_status": sub_status,
        "questions_used": user.questions_today,
        "questions_total": QUESTIONS_PER_DAY,
        "forecast_time": user.forecast_time,
        "push_status": "Вкл" if user.push_transits else "Выкл",
        "timezone": user.residence_tz or "Europe/Moscow"
    }


async def notify_admin_new_user(client: Client, user: User):
    """Уведомление админа о новом пользователе"""
    try:
        text = f"""👤 <b>Новый пользователь!</b>

ID: <code>{user.telegram_id}</code>
Имя: {user.display_name}
Username: @{user.username if user.username else 'нет'}

Натальные данные: {'✅' if user.natal_data_complete else '❌ Не заполнены'}"""

        await client.send_message(ADMIN_ID, text)
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")


# ============== ОБРАБОТЧИКИ ==============

async def start_handler(client: Client, message: Message):
    """Обработчик команды /start"""
    logger.info(f"Получена команда /start от {message.from_user.id}")

    user, created = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    if created:
        await notify_admin_new_user(client, user)
        logger.info(f"Новый пользователь: {user.telegram_id}")

    # Определяем какой экран показать
    if not user.natal_data_complete:
        # Нет натальных данных
        await message.reply(
            WELCOME_NO_DATA_TEXT,
            reply_markup=get_welcome_keyboard(
                has_natal_data=user.natal_data_complete,
                user_id=user.telegram_id
            )
        )
    elif not user.has_active_subscription():
        # Нет подписки
        info = format_user_info(user)
        await message.reply(
            WELCOME_NO_SUB_TEXT.format(price=SUBSCRIPTION_PRICE, **info),
            reply_markup=get_no_subscription_keyboard(user_id=user.telegram_id)
        )
    else:
        # Активный пользователь
        info = format_user_info(user)
        questions_left = user.get_questions_remaining()
        await message.reply(
            MAIN_MENU_TEXT.format(**info),
            reply_markup=get_main_menu_keyboard(questions_left, user.telegram_id)
        )


async def webapp_handler(client: Client, message: Message):
    """Обработчик команды /webapp - открывает Mini App"""
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    from config import WEBAPP_URL

    user, _ = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    if not user.natal_data_complete:
        await message.reply(
            "⚠️ Ваш профиль ещё не настроен.\n\n"
            "Напишите астрологу для внесения данных.",
            reply_markup=get_welcome_keyboard(user_id=user.telegram_id)
        )
        return

    await message.reply(
        "🌟 <b>Астро-прогноз</b>\n\n"
        "Нажмите кнопку чтобы открыть приложение:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🌟 ОТКРЫТЬ ПРОГНОЗЫ",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/webapp")
            )]
        ])
    )


async def forecast_command_handler(client: Client, message: Message):
    """Обработчик команды /forecast"""
    user, _ = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    if not user.natal_data_complete:
        await message.reply(
            "⚠️ Для получения прогноза нужны ваши натальные данные.\n\n"
            "Напишите астрологу для настройки профиля.",
            reply_markup=get_welcome_keyboard(user_id=user.telegram_id)
        )
        return

    if not user.has_active_subscription():
        await message.reply(
            "❌ У вас нет активной подписки.\n\n"
            f"Стоимость: {SUBSCRIPTION_PRICE} ₽/месяц",
            reply_markup=get_no_subscription_keyboard(user_id=user.telegram_id)
        )
        return

    # Показываем главное меню с кнопкой прогноза
    info = format_user_info(user)
    await message.reply(
        MAIN_MENU_TEXT.format(**info),
        reply_markup=get_main_menu_keyboard(user.get_questions_remaining(), user.telegram_id)
    )


async def settings_command_handler(client: Client, message: Message):
    """Обработчик команды /settings — перенаправляет на MiniApp"""
    from pyrogram.types import WebAppInfo

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⚙️ Открыть настройки",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/webapp#settings")
        )],
        [InlineKeyboardButton("◀️ В главное меню", callback_data="back_main")]
    ])

    await message.reply(
        "⚙️ <b>Настройки</b>\n\n"
        "Все настройки доступны в приложении прогнозов.\n"
        "Нажмите кнопку ниже, чтобы открыть настройки:",
        reply_markup=keyboard
    )


async def help_command_handler(client: Client, message: Message):
    """Обработчик команды /help"""
    await message.reply(HELP_TEXT, reply_markup=get_help_keyboard())


async def support_command_handler(client: Client, message: Message):
    """Обработчик команды /support"""
    await message.reply(SUPPORT_TEXT, reply_markup=get_support_keyboard())


async def callback_handler(client: Client, callback: CallbackQuery):
    """Обработчик callback-кнопок"""
    data = callback.data
    user_id = callback.from_user.id

    try:
        user = User.get_by_id(user_id)
    except User.DoesNotExist:
        user, _ = get_or_create_user(
            telegram_id=user_id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name
        )

    # Игнорируемые callback
    if data in ["cal_ignore", "adm_ignore"]:
        await callback.answer()
        return

    # === НАВИГАЦИЯ ===

    if data == "back_main":
        await show_main_menu(callback, user)

    elif data == "back_main_keep":
        # Сохраняем прогноз, отправляем меню новым сообщением
        await show_main_menu(callback, user, preserve_message=True)

    elif data == "how_it_works":
        await callback.answer()
        await callback.message.edit_text(
            HELP_TEXT,
            reply_markup=get_help_keyboard()
        )

    # === СПРАВКА ===

    elif data == "help":
        await callback.answer()
        await callback.message.edit_text(
            HELP_TEXT,
            reply_markup=get_help_keyboard()
        )

    elif data == "help_method":
        await callback.answer()
        await callback.message.edit_text(
            HELP_METHOD_TEXT,
            reply_markup=get_help_keyboard()
        )

    # === ПРОГНОЗЫ ===

    elif data == "forecast_today":
        await handle_forecast_today(client, callback, user)

    elif data == "forecast_period":
        await callback.answer()
        await callback.message.edit_text(
            PERIOD_TEXT,
            reply_markup=get_period_keyboard()
        )

    elif data in ["forecast_3d", "forecast_week", "forecast_month"]:
        period_map = {
            "forecast_3d": "3d",
            "forecast_week": "week",
            "forecast_month": "month"
        }
        await handle_forecast_period(client, callback, user, period_map[data])

    elif data == "forecast_date":
        await callback.answer()
        await callback.message.edit_text(
            CALENDAR_TEXT,
            reply_markup=get_calendar_keyboard()
        )

    elif data.startswith("cal_nav_"):
        # Навигация по календарю
        try:
            parts = data.split("_")
            if len(parts) >= 4:
                year, month = int(parts[2]), int(parts[3])
                await callback.answer()
                await callback.message.edit_reply_markup(
                    reply_markup=get_calendar_keyboard(year, month)
                )
            else:
                await callback.answer("Ошибка навигации", show_alert=True)
        except (ValueError, IndexError):
            await callback.answer("Некорректные данные", show_alert=True)

    elif data.startswith("cal_day_"):
        # Выбор даты
        date_str = data.replace("cal_day_", "")
        await handle_forecast_date(client, callback, user, date_str)

    # === ВОПРОСЫ ===

    elif data == "ask_question":
        await handle_ask_question(client, callback, user)

    elif data.startswith("ask_about_forecast:"):
        forecast_id = parse_callback_int(data, "ask_about_forecast:")
        if forecast_id is None:
            await callback.answer("Ошибка данных", show_alert=True)
            return
        await handle_ask_about_forecast(client, callback, user, forecast_id)

    # === НАСТРОЙКИ (перенаправление на MiniApp) ===

    elif data in ["settings", "settings_time", "settings_push_on", "settings_push_off"] or data.startswith("set_time_"):
        from pyrogram.types import WebAppInfo
        await callback.answer()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⚙️ Открыть настройки",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/webapp#settings")
            )],
            [InlineKeyboardButton("◀️ В главное меню", callback_data="back_main")]
        ])
        await callback.message.edit_text(
            "⚙️ <b>Настройки</b>\n\n"
            "Все настройки доступны в приложении прогнозов.\n"
            "Нажмите кнопку ниже, чтобы открыть настройки:",
            reply_markup=keyboard
        )

    # === ПОДДЕРЖКА ===

    elif data == "support":
        await callback.answer()
        await callback.message.edit_text(
            SUPPORT_TEXT,
            reply_markup=get_support_keyboard()
        )

    elif data == "support_new":
        await callback.answer()
        set_support_state(user.telegram_id, "waiting_message")
        await callback.message.edit_text(
            SUPPORT_NEW_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Отмена", callback_data="support")]
            ])
        )

    elif data == "support_list":
        await callback.answer()
        # Получаем тикеты пользователя
        tickets = SupportTicket.select().where(
            SupportTicket.user == user
        ).order_by(SupportTicket.created_at.desc()).limit(10)

        if not tickets.count():
            await callback.message.edit_text(
                SUPPORT_NO_TICKETS_TEXT,
                reply_markup=get_support_keyboard()
            )
            return

        # Форматируем список тикетов
        status_icons = {"open": "🟡", "answered": "🟢", "closed": "⚪"}
        tickets_list = []
        for ticket in tickets:
            icon = status_icons.get(ticket.status, "⚪")
            date_str = ticket.created_at.strftime("%d.%m.%Y %H:%M")
            preview = ticket.last_message_preview or "Нет сообщений"
            tickets_list.append(f"{icon} <b>{date_str}</b>\n   {preview}")

        await callback.message.edit_text(
            SUPPORT_LIST_TEXT.format(tickets_list="\n\n".join(tickets_list)),
            reply_markup=get_support_keyboard()
        )

    # === ОПЛАТА ===

    elif data in ["payment_new", "payment_extend"]:
        await callback.answer()
        await callback.message.edit_text(
            PAYMENT_TEXT.format(price=SUBSCRIPTION_PRICE),
            reply_markup=get_payment_keyboard()
        )

    elif data == "payment_create":
        await callback.answer("Создаю платёж...")

        # Проверяем конфигурацию YooKassa
        if not yookassa_service.is_configured():
            await callback.message.edit_text(
                "❌ Платёжная система временно недоступна.\n\n"
                f"Свяжитесь с администратором @{ADMIN_USERNAME} для оплаты.",
                reply_markup=get_payment_keyboard()
            )
            return

        # Создаём платёж (в отдельном потоке, чтобы не блокировать event loop)
        try:
            payment_result = await asyncio.to_thread(
                yookassa_service.create_payment,
                user_id=user.telegram_id,
                amount=SUBSCRIPTION_PRICE,
                description=f"Подписка Астро-бот для {user.display_name}"
            )
        except Exception as e:
            logger.error(f"Исключение при создании платежа: {e}", exc_info=True)
            payment_result = None

        if not payment_result:
            await callback.message.edit_text(
                "❌ Не удалось создать платёж. Попробуйте позже.",
                reply_markup=get_payment_keyboard()
            )
            return

        # Создаём запись подписки со статусом pending
        from decimal import Decimal
        Subscription.create_for_user(
            user=user,
            amount=Decimal(str(payment_result["amount"])),
            payment_id=payment_result["payment_id"]
        )

        # Показываем ссылку на оплату
        await callback.message.edit_text(
            PAYMENT_PENDING_TEXT,
            reply_markup=get_payment_pending_keyboard(payment_result["confirmation_url"])
        )

    elif data == "payment_check":
        await callback.answer("Проверяю оплату...")

        # Ищем последний pending платёж пользователя
        pending_sub = Subscription.select().where(
            Subscription.user == user,
            Subscription.status == "pending"
        ).order_by(Subscription.created_at.desc()).first()

        if not pending_sub or not pending_sub.payment_id:
            await callback.message.edit_text(
                PAYMENT_NOT_FOUND_TEXT,
                reply_markup=get_payment_keyboard()
            )
            return

        # Проверяем статус в YooKassa (в отдельном потоке)
        try:
            status = await asyncio.to_thread(
                yookassa_service.check_payment_status, pending_sub.payment_id
            )
        except Exception as e:
            logger.error(f"Исключение при проверке статуса платежа: {e}", exc_info=True)
            status = None

        if not status:
            await callback.message.edit_text(
                "❌ Не удалось проверить статус платежа. Попробуйте позже.",
                reply_markup=get_payment_keyboard()
            )
            return

        if status["status"] == "succeeded" and status["paid"]:
            # Активируем подписку
            pending_sub.activate()

            # Уведомляем админа об оплате
            try:
                await notify_admin_payment(callback._client, user)
            except Exception as e:
                logger.error(f"Ошибка уведомления админа об оплате: {e}")

            # Проверяем, заполнил ли пользователь данные
            if not user.user_data_submitted:
                # Показываем кнопку "Заполнить данные"
                await callback.message.edit_text(
                    PAYMENT_SUCCESS_TEXT + "\n\n📝 <i>Теперь заполните ваши данные для получения прогнозов!</i>",
                    reply_markup=get_after_payment_keyboard()
                )
            else:
                # Данные уже заполнены, показываем главное меню
                questions_left = user.get_questions_remaining()
                await callback.message.edit_text(
                    PAYMENT_SUCCESS_TEXT,
                    reply_markup=get_main_menu_keyboard(questions_left, user.telegram_id)
                )

        elif status["status"] == "pending":
            # Ещё не оплачен
            payment_url = f"https://yoomoney.ru/checkout/payments/{pending_sub.payment_id}"
            await callback.message.edit_text(
                PAYMENT_STILL_PENDING_TEXT,
                reply_markup=get_payment_pending_keyboard(payment_url)
            )

        else:
            # Отменён или ошибка
            pending_sub.status = "expired"
            pending_sub.save()
            await callback.message.edit_text(
                PAYMENT_FAILED_TEXT,
                reply_markup=get_payment_keyboard()
            )

    elif data == "payment_cancel":
        # Отменяем pending платёж если есть
        pending_sub = Subscription.select().where(
            Subscription.user == user,
            Subscription.status == "pending"
        ).order_by(Subscription.created_at.desc()).first()

        if pending_sub and pending_sub.payment_id:
            try:
                await asyncio.to_thread(
                    yookassa_service.cancel_payment, pending_sub.payment_id
                )
            except Exception as e:
                logger.error(f"Ошибка отмены платежа: {e}")
            pending_sub.status = "expired"
            pending_sub.save()

        await show_main_menu(callback, user)

    # === ОЗВУЧКА ===

    elif data.startswith("voice_forecast:"):
        forecast_id = parse_callback_int(data, "voice_forecast:")
        if forecast_id is None:
            await callback.answer("Ошибка данных", show_alert=True)
            return
        await handle_voice_forecast(client, callback, forecast_id)

    elif data == "voice_answer":
        await handle_voice_answer(client, callback, user)

    # === АДМИН-ПАНЕЛЬ ===

    elif data == "admin_panel":
        from handlers.admin import show_admin_panel
        await show_admin_panel(client, callback)


async def show_main_menu(callback: CallbackQuery, user: User, preserve_message: bool = False):
    """
    Показать главное меню

    Args:
        callback: CallbackQuery
        user: User
        preserve_message: Если True — отправляет новое сообщение, сохраняя текущее (для прогнозов)
    """
    await callback.answer()

    if not user.natal_data_complete:
        text = WELCOME_NO_DATA_TEXT
        keyboard = get_welcome_keyboard(user_id=user.telegram_id)
    elif not user.has_active_subscription():
        info = format_user_info(user)
        text = WELCOME_NO_SUB_TEXT.format(price=SUBSCRIPTION_PRICE, **info)
        keyboard = get_no_subscription_keyboard(user_id=user.telegram_id)
    else:
        info = format_user_info(user)
        questions_left = user.get_questions_remaining()
        text = MAIN_MENU_TEXT.format(**info)
        keyboard = get_main_menu_keyboard(questions_left, user.telegram_id)

    if preserve_message:
        # Убираем кнопки из прогноза, отправляем меню новым сообщением
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        await callback.message.reply(text, reply_markup=keyboard)
    else:
        await callback.message.edit_text(text, reply_markup=keyboard)


async def process_support_message(client: Client, message: Message, user: User) -> bool:
    """Обработка сообщения поддержки"""
    state = get_support_state(user.telegram_id)

    if state.get("state") != "waiting_message":
        return False

    message_text = message.text.strip() if message.text else ""
    if not message_text:
        return True

    try:
        # Создаём тикет
        ticket = SupportTicket.create(user=user, status="open")

        # Добавляем сообщение
        SupportMessage.create(
            ticket=ticket,
            sender_type="user",
            sender_id=user.telegram_id,
            message_text=message_text
        )

        clear_support_state(user.telegram_id)

        # Уведомляем пользователя
        await message.reply(
            SUPPORT_SENT_TEXT,
            reply_markup=get_support_keyboard()
        )

        # Уведомляем админа
        try:
            await client.send_message(
                ADMIN_ID,
                f"📩 <b>Новое обращение в поддержку</b>\n\n"
                f"👤 Пользователь: {user.display_name}\n"
                f"🆔 ID: <code>{user.telegram_id}</code>\n\n"
                f"💬 {message_text}"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа: {e}")

        return True

    except Exception as e:
        logger.error(f"Ошибка создания тикета: {e}")
        await message.reply("❌ Не удалось отправить сообщение. Попробуйте позже.")
        clear_support_state(user.telegram_id)
        return True


def register_handlers(app: Client):
    """Регистрация обработчиков"""
    from pyrogram.handlers import MessageHandler, CallbackQueryHandler

    logger.info("Регистрация обработчиков start.py...")

    # Команды
    app.add_handler(MessageHandler(start_handler, filters.command("start") & filters.private))
    logger.info("Обработчик /start зарегистрирован")
    app.add_handler(MessageHandler(help_command_handler, filters.command("help") & filters.private))
    app.add_handler(MessageHandler(support_command_handler, filters.command("support") & filters.private))

    # Callback кнопки
    callback_filter = filters.regex(
        r"^(back_main|back_main_keep|how_it_works|help|help_method|"
        r"forecast_today|forecast_period|forecast_3d|forecast_week|forecast_month|"
        r"forecast_date|cal_nav_|cal_day_|cal_ignore|"
        r"ask_question|ask_about_forecast:|"
        r"settings|settings_time|set_time_|settings_push_on|settings_push_off|"
        r"support|support_new|support_list|"
        r"payment_new|payment_extend|payment_create|payment_check|payment_cancel|"
        r"voice_forecast:|voice_answer|admin_panel)"
    )
    app.add_handler(CallbackQueryHandler(callback_handler, callback_filter))

    # Обработчик текстовых сообщений для поддержки
    async def support_text_handler(client: Client, message: Message):
        try:
            user = User.get_by_id(message.from_user.id)
        except User.DoesNotExist:
            return

        # Проверяем состояние поддержки
        if await process_support_message(client, message, user):
            return

    support_filter = filters.text & filters.private & ~filters.command(["start", "help", "admin", "webapp", "forecast", "settings", "support"])
    app.add_handler(MessageHandler(support_text_handler, support_filter), group=1)

    logger.info("Все обработчики start.py зарегистрированы")
