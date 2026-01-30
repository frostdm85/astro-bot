#!/usr/bin/env python3
# coding: utf-8

"""
Обработчик сбора данных от пользователей
- FSM для сбора birth_date, birth_time, birth_city, current_city, marriage_date, marriage_city
- Валидация данных
- Уведомление админа
"""

import logging
import time as time_module
from datetime import datetime, date

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database.models import User
from services.data_collection_service import notify_admin_data_submitted

logger = logging.getLogger(__name__)

# FSM состояния
user_data_states = {}  # {user_id: {"state": "...", "data": {...}, "created_at": timestamp}}


def set_data_state(user_id: int, state: str, data: dict = None):
    """Установить состояние сбора данных"""
    if user_id not in user_data_states:
        user_data_states[user_id] = {"data": {}}

    user_data_states[user_id]["state"] = state
    user_data_states[user_id]["created_at"] = time_module.time()

    if data:
        user_data_states[user_id]["data"].update(data)


def get_data_state(user_id: int) -> dict:
    """Получить состояние сбора данных"""
    return user_data_states.get(user_id, {"state": None, "data": {}})


def clear_data_state(user_id: int):
    """Очистить состояние"""
    if user_id in user_data_states:
        del user_data_states[user_id]


# ============== ВАЛИДАЦИЯ ==============

def validate_date(text: str) -> tuple[bool, str, date]:
    """
    Валидация даты в формате ДД.ММ.ГГГГ

    Returns:
        (is_valid, error_message, parsed_date)
    """
    try:
        parsed = datetime.strptime(text, "%d.%m.%Y").date()

        # Проверка адекватности даты
        if parsed.year < 1900:
            return False, "Год должен быть не раньше 1900", None
        if parsed > date.today():
            return False, "Дата не может быть в будущем", None

        return True, None, parsed
    except ValueError:
        return False, "Неверный формат. Используйте ДД.ММ.ГГГГ (например: 15.06.1990)", None


def validate_time(text: str) -> tuple[bool, str, str]:
    """
    Валидация времени в формате ЧЧ:ММ

    Returns:
        (is_valid, error_message, time_string)
    """
    try:
        # Пробуем распарсить
        parsed = datetime.strptime(text, "%H:%M")
        return True, None, text
    except ValueError:
        return False, "Неверный формат. Используйте ЧЧ:ММ (например: 14:30)", None


def validate_city(text: str) -> tuple[bool, str, str]:
    """
    Валидация названия города

    Returns:
        (is_valid, error_message, city_name)
    """
    text = text.strip()

    if len(text) < 2:
        return False, "Название города слишком короткое", None

    if len(text) > 100:
        return False, "Название города слишком длинное", None

    return True, None, text


# ============== ТЕКСТЫ ==============

DATA_START_TEXT = """📝 <b>Заполнение данных для прогнозов</b>

Для точных астрологических прогнозов нужна следующая информация:

1️⃣ Дата рождения (ДД.ММ.ГГГГ)
2️⃣ Точное время рождения (ЧЧ:ММ)
3️⃣ Город рождения
4️⃣ Город проживания
5️⃣ Дата 1-го брака <i>(необязательно)</i>
6️⃣ Город регистрации брака <i>(необязательно)</i>

━━━━━━━━━━━━━━━━━━━
<b>Шаг 1/6:</b> Введите дату рождения

<i>Формат:</i> <code>ДД.ММ.ГГГГ</code>
<i>Пример:</i> 15.06.1990"""

DATA_BIRTH_TIME_TEXT = """<b>Шаг 2/6:</b> Введите точное время рождения

<i>Формат:</i> <code>ЧЧ:ММ</code>
<i>Пример:</i> 14:30

⚠️ Если точное время неизвестно, укажите приблизительное."""

DATA_BIRTH_CITY_TEXT = """<b>Шаг 3/6:</b> Введите город рождения

<i>Пример:</i> Москва"""

DATA_CURRENT_CITY_TEXT = """<b>Шаг 4/6:</b> Введите город проживания

<i>Пример:</i> Санкт-Петербург"""

DATA_MARRIAGE_DATE_TEXT = """<b>Шаг 5/6:</b> Введите дату регистрации 1-го брака

<i>Формат:</i> <code>ДД.ММ.ГГГГ</code>
<i>Пример:</i> 20.07.2015

Если не было брака, нажмите кнопку "Пропустить"."""

DATA_MARRIAGE_CITY_TEXT = """<b>Шаг 6/6:</b> Введите город регистрации брака

<i>Пример:</i> Екатеринбург

Если не помните, нажмите кнопку "Пропустить"."""

DATA_COMPLETE_TEXT = """✅ <b>Данные сохранены!</b>

Ваши данные отправлены астрологу для обработки.

В течение 24 часов вы получите доступ к персональным прогнозам.

Спасибо! 🌟"""


# ============== ОБРАБОТЧИКИ ==============

async def handle_data_start(client: Client, callback: CallbackQuery, user: User):
    """Начало сбора данных"""
    await callback.answer()

    # Устанавливаем состояние ожидания даты рождения
    set_data_state(user.telegram_id, "birth_date_waiting")

    await callback.message.edit_text(
        DATA_START_TEXT,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="data:cancel")]
        ])
    )


async def handle_data_cancel(callback: CallbackQuery):
    """Отмена сбора данных"""
    await callback.answer()
    clear_data_state(callback.from_user.id)

    from handlers.start import show_main_menu
    from database.models import User

    user = User.get_by_id(callback.from_user.id)
    await show_main_menu(callback, user)


async def process_data_message(client: Client, message: Message, user: User) -> bool:
    """
    Обработка сообщения в процессе сбора данных

    Returns:
        True если сообщение обработано
    """
    state_data = get_data_state(user.telegram_id)
    state = state_data.get("state")
    data = state_data.get("data", {})

    if not state:
        return False

    text = message.text.strip() if message.text else ""

    # ===== ШАГ 1: Дата рождения =====
    if state == "birth_date_waiting":
        is_valid, error, parsed_date = validate_date(text)

        if not is_valid:
            await message.reply(f"❌ {error}\n\nПопробуйте ещё раз:")
            return True

        # Сохраняем дату
        data["birth_date"] = parsed_date
        set_data_state(user.telegram_id, "birth_time_waiting", data)

        await message.reply(
            DATA_BIRTH_TIME_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="data:cancel")]
            ])
        )
        return True

    # ===== ШАГ 2: Время рождения =====
    elif state == "birth_time_waiting":
        is_valid, error, time_str = validate_time(text)

        if not is_valid:
            await message.reply(f"❌ {error}\n\nПопробуйте ещё раз:")
            return True

        # Сохраняем время
        data["birth_time"] = time_str
        set_data_state(user.telegram_id, "birth_city_waiting", data)

        await message.reply(
            DATA_BIRTH_CITY_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="data:cancel")]
            ])
        )
        return True

    # ===== ШАГ 3: Город рождения =====
    elif state == "birth_city_waiting":
        is_valid, error, city = validate_city(text)

        if not is_valid:
            await message.reply(f"❌ {error}\n\nПопробуйте ещё раз:")
            return True

        # Сохраняем город
        data["birth_city"] = city
        set_data_state(user.telegram_id, "current_city_waiting", data)

        await message.reply(
            DATA_CURRENT_CITY_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="data:cancel")]
            ])
        )
        return True

    # ===== ШАГ 4: Текущий город =====
    elif state == "current_city_waiting":
        is_valid, error, city = validate_city(text)

        if not is_valid:
            await message.reply(f"❌ {error}\n\nПопробуйте ещё раз:")
            return True

        # Сохраняем город
        data["current_city"] = city
        set_data_state(user.telegram_id, "marriage_date_waiting", data)

        await message.reply(
            DATA_MARRIAGE_DATE_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ Пропустить", callback_data="data:skip_marriage")],
                [InlineKeyboardButton("❌ Отмена", callback_data="data:cancel")]
            ])
        )
        return True

    # ===== ШАГ 5: Дата брака =====
    elif state == "marriage_date_waiting":
        is_valid, error, parsed_date = validate_date(text)

        if not is_valid:
            await message.reply(f"❌ {error}\n\nПопробуйте ещё раз или нажмите \"Пропустить\":")
            return True

        # Сохраняем дату брака
        data["marriage_date"] = parsed_date
        set_data_state(user.telegram_id, "marriage_city_waiting", data)

        await message.reply(
            DATA_MARRIAGE_CITY_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ Пропустить", callback_data="data:skip_marriage_city")],
                [InlineKeyboardButton("❌ Отмена", callback_data="data:cancel")]
            ])
        )
        return True

    # ===== ШАГ 6: Город брака =====
    elif state == "marriage_city_waiting":
        is_valid, error, city = validate_city(text)

        if not is_valid:
            await message.reply(f"❌ {error}\n\nПопробуйте ещё раз или нажмите \"Пропустить\":")
            return True

        # Сохраняем город брака
        data["marriage_city"] = city

        # ===== ФИНАЛЬНОЕ СОХРАНЕНИЕ =====
        try:
            await save_user_data(client, user, data)
            clear_data_state(user.telegram_id)

            await message.reply(
                DATA_COMPLETE_TEXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 В главное меню", callback_data="back_main")]
                ])
            )
        except ValueError as e:
            logger.error(f"Валидация данных не прошла для user {user.telegram_id}: {e}")
            await message.reply(
                f"❌ <b>Ошибка сохранения данных</b>\n\n{str(e)}\n\n"
                f"Пожалуйста, обратитесь в поддержку."
            )
        except Exception as e:
            logger.error(f"Неожиданная ошибка при сохранении данных user {user.telegram_id}: {e}")
            await message.reply(
                "❌ <b>Произошла ошибка</b>\n\n"
                "Пожалуйста, попробуйте ещё раз позже или обратитесь в поддержку."
            )
        return True

    return False


async def handle_skip_marriage(client: Client, callback: CallbackQuery, user: User):
    """Пропустить данные о браке"""
    await callback.answer()

    state_data = get_data_state(user.telegram_id)
    data = state_data.get("data", {})

    # ===== ФИНАЛЬНОЕ СОХРАНЕНИЕ БЕЗ ДАННЫХ О БРАКЕ =====
    try:
        await save_user_data(client, user, data)
        clear_data_state(user.telegram_id)

        await callback.message.edit_text(
            DATA_COMPLETE_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_main")]
            ])
        )
    except ValueError as e:
        logger.error(f"Валидация данных не прошла для user {user.telegram_id}: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка сохранения данных</b>\n\n{str(e)}\n\n"
            f"Пожалуйста, обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_main")]
            ])
        )
    except Exception as e:
        logger.error(f"Неожиданная ошибка при сохранении данных user {user.telegram_id}: {e}")
        await callback.message.edit_text(
            "❌ <b>Произошла ошибка</b>\n\n"
            "Пожалуйста, попробуйте ещё раз позже или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_main")]
            ])
        )


async def handle_skip_marriage_city(client: Client, callback: CallbackQuery, user: User):
    """Пропустить город брака (но дата брака уже указана)"""
    await callback.answer()

    state_data = get_data_state(user.telegram_id)
    data = state_data.get("data", {})

    # Сохраняем без города брака
    try:
        await save_user_data(client, user, data)
        clear_data_state(user.telegram_id)

        await callback.message.edit_text(
            DATA_COMPLETE_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_main")]
            ])
        )
    except ValueError as e:
        logger.error(f"Валидация данных не прошла для user {user.telegram_id}: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка сохранения данных</b>\n\n{str(e)}\n\n"
            f"Пожалуйста, обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_main")]
            ])
        )
    except Exception as e:
        logger.error(f"Неожиданная ошибка при сохранении данных user {user.telegram_id}: {e}")
        await callback.message.edit_text(
            "❌ <b>Произошла ошибка</b>\n\n"
            "Пожалуйста, попробуйте ещё раз позже или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_main")]
            ])
        )


async def save_user_data(client: Client, user: User, data: dict):
    """Сохранить данные пользователя в БД и уведомить админа"""
    from datetime import datetime

    # ВАЛИДАЦИЯ: Проверяем наличие всех обязательных полей
    required_fields = ["birth_date", "birth_time", "birth_city", "current_city"]
    missing_fields = [field for field in required_fields if not data.get(field)]

    if missing_fields:
        logger.error(
            f"Попытка сохранения неполных данных user {user.telegram_id}. "
            f"Отсутствуют поля: {missing_fields}"
        )
        raise ValueError(f"Отсутствуют обязательные поля: {', '.join(missing_fields)}")

    # Обновляем данные пользователя
    user.birth_date = data.get("birth_date")
    user.birth_time = datetime.strptime(data.get("birth_time"), "%H:%M").time() if data.get("birth_time") else None
    user.birth_place = data.get("birth_city")
    user.residence_place = data.get("current_city")
    user.marriage_date = data.get("marriage_date")
    user.marriage_city = data.get("marriage_city")

    # Устанавливаем флаг пользовательского заполнения
    user.user_data_submitted = True
    user.user_data_submitted_at = datetime.now()

    # КРИТИЧНО: Сохраняем ПЕРЕД уведомлением админа
    user.save()
    logger.info(f"Данные пользователя {user.telegram_id} сохранены в БД")

    # Уведомляем админа (не критично, обрабатываем ошибки)
    try:
        has_paid = user.has_active_subscription()
        await notify_admin_data_submitted(client, user, has_paid=has_paid)
    except Exception as e:
        logger.error(f"Ошибка уведомления админа о данных user {user.telegram_id}: {e}")


def register_handlers(app: Client):
    """Регистрация обработчиков"""
    from pyrogram.handlers import CallbackQueryHandler, MessageHandler
    from pyrogram import filters

    logger.info("Регистрация обработчиков data_collection.py...")

    # Callback обработчики
    data_callback_filter = filters.regex(r"^(data:start|data:cancel|data:skip_marriage|data:skip_marriage_city)$")

    async def data_callback_router(client: Client, callback: CallbackQuery):
        """Роутер callback-кнопок сбора данных"""
        data = callback.data

        try:
            user = User.get_by_id(callback.from_user.id)
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        if data == "data:start":
            await handle_data_start(client, callback, user)
        elif data == "data:cancel":
            await handle_data_cancel(callback)
        elif data == "data:skip_marriage":
            await handle_skip_marriage(client, callback, user)
        elif data == "data:skip_marriage_city":
            await handle_skip_marriage_city(client, callback, user)

    app.add_handler(CallbackQueryHandler(data_callback_router, data_callback_filter))

    # Текстовые сообщения для FSM
    async def data_text_handler(client: Client, message: Message):
        try:
            user = User.get_by_id(message.from_user.id)
        except User.DoesNotExist:
            return

        # Обрабатываем сообщение если пользователь в процессе сбора данных
        await process_data_message(client, message, user)

    data_text_filter = filters.text & filters.private & ~filters.command([
        "start", "help", "admin", "webapp", "forecast", "settings", "support"
    ])
    app.add_handler(MessageHandler(data_text_handler, data_text_filter), group=2)

    logger.info("Обработчики data_collection.py зарегистрированы")
