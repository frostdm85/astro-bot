#!/usr/bin/env python3
# coding: utf-8

"""
Обработчики прогнозов — генерация и отправка астрологических прогнозов
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID
from database.models import User, Forecast
from services.astro_engine import (
    get_transits,
    calculate_houses,
    get_planet_house,
    generate_full_forecast_data
)
from services.groq_client import generate_forecast
from services.tts_service import text_to_speech
from services.geocoder import get_timezone_offset
from data.shestopalov import (
    check_active_formulas,
    get_transit_interpretation,
    get_transit_priority
)
from utils.keyboards import get_forecast_keyboard, get_period_keyboard

logger = logging.getLogger(__name__)


# ============== ЧЕЛОВЕКОЧИТАЕМЫЕ ОШИБКИ ==============

ERROR_MESSAGES = {
    # Натальные данные
    "natal_incomplete": "Для прогноза нужны ваши данные рождения. Заполните их в настройках.",
    "natal_invalid": "Данные рождения некорректны. Проверьте введённую информацию.",

    # AI/Groq
    "ai_timeout": "Сервис временно недоступен. Попробуйте через минуту.",
    "ai_no_response": "Не удалось получить ответ. Попробуйте ещё раз.",
    "ai_overloaded": "Сервер перегружен. Попробуйте через несколько минут.",

    # TTS
    "tts_failed": "Не удалось озвучить прогноз. Попробуйте позже.",
    "tts_not_found": "Прогноз не найден. Сначала сгенерируйте текстовый прогноз.",

    # Общие
    "unknown_error": "Произошла ошибка. Попробуйте позже или обратитесь в поддержку.",
    "network_error": "Проблема с соединением. Проверьте интернет и попробуйте снова.",
}


def get_user_error(error: Exception) -> str:
    """
    Преобразует техническую ошибку в понятное пользователю сообщение
    """
    error_str = str(error).lower()

    # Groq/AI ошибки
    if "timeout" in error_str or "timed out" in error_str:
        return ERROR_MESSAGES["ai_timeout"]
    if "rate limit" in error_str or "too many requests" in error_str:
        return ERROR_MESSAGES["ai_overloaded"]
    if "connection" in error_str or "network" in error_str:
        return ERROR_MESSAGES["network_error"]
    if "groq" in error_str or "api" in error_str:
        return ERROR_MESSAGES["ai_no_response"]

    # Астрологические расчёты
    if "ephemeris" in error_str or "swisseph" in error_str:
        return ERROR_MESSAGES["unknown_error"]

    # По умолчанию
    return ERROR_MESSAGES["unknown_error"]


# ============== ТЕКСТЫ ==============

FORECAST_GENERATING_TEXT = """🔮 <b>Прогноз на {date}</b>

⏳ Генерирую персональный прогноз...

<i>Расчёт транзитов и анализ аспектов...</i>"""

FORECAST_ERROR_TEXT = """❌ <b>Ошибка генерации прогноза</b>

К сожалению, не удалось сгенерировать прогноз. Попробуйте позже или обратитесь в поддержку.

<i>Ошибка: {error}</i>"""

FORECAST_TEXT = """🔮 <b>Прогноз на {date}</b>

━━━━━━━━━━━━━━━━━━━━━━━━

{content}

━━━━━━━━━━━━━━━━━━━━━━━━

"""

PERIOD_FORECAST_TEXT = """📅 <b>Прогноз на {period}</b>
<i>{date_range}</i>

━━━━━━━━━━━━━━━━━━━━━━━━

{content}

━━━━━━━━━━━━━━━━━━━━━━━━
"""


# ============== ГЕНЕРАЦИЯ ПРОГНОЗА ==============

async def generate_daily_forecast(
    user: User,
    target_date: date = None,
    save_to_db: bool = True
) -> dict:
    """
    Генерация дневного прогноза

    Args:
        user: Объект пользователя с натальными данными
        target_date: Дата прогноза (по умолчанию — сегодня)
        save_to_db: Сохранять ли прогноз в БД

    Returns:
        Словарь с данными прогноза
    """
    if target_date is None:
        target_date = date.today()

    # Проверяем наличие натальных данных
    if not user.natal_data_complete:
        return {
            "success": False,
            "error": "Натальные данные не заполнены"
        }

    try:
        # Вычисляем смещение часового пояса с учётом даты рождения
        timezone_name = user.birth_tz or "Europe/Moscow"
        timezone_hours = get_timezone_offset(timezone_name, user.birth_date)

        # Получаем полные данные для прогноза
        forecast_data = generate_full_forecast_data(
            birth_date=user.birth_date,
            birth_time=user.birth_time,
            birth_lat=user.birth_lat,
            birth_lon=user.birth_lon,
            residence_lat=user.residence_lat or user.birth_lat,
            residence_lon=user.residence_lon or user.birth_lon,
            target_date=target_date,
            timezone_hours=timezone_hours
        )

        # Формируем список транзитов для пользователя (текстовый вывод)
        transits_display = format_transits_list(forecast_data)

        # Формируем данные для AI
        transits_text = format_transits_for_ai(forecast_data)

        # Подготавливаем transits_list для извлечения формул
        transits_list = forecast_data.get("aspects_detailed", [])

        # Генерируем расшифровку через AI
        ai_response = await generate_forecast(
            transits_data=transits_text,
            transits_list=transits_list,
            user_name=user.display_name,
            forecast_type="daily",
            target_date=target_date.strftime("%d.%m.%Y")
        )

        if not ai_response:
            return {
                "success": False,
                "error": "Не удалось получить ответ от AI"
            }

        # Собираем итоговый текст: список транзитов + расшифровка
        full_text = f"{transits_display}\n\n<b>📖 РАСШИФРОВКА:</b>\n\n{ai_response}"

        # Сохраняем в БД
        forecast_record = None
        if save_to_db:
            import json
            forecast_record = Forecast.create(
                user=user,
                forecast_type="daily",
                target_date=target_date,
                transits_data=json.dumps(forecast_data, ensure_ascii=False, default=str),
                forecast_text=ai_response
            )

        return {
            "success": True,
            "forecast_id": forecast_record.id if forecast_record else None,
            "text": full_text,
            "date": target_date,
            "transits": forecast_data.get("aspects_detailed", []),
            "active_formulas": forecast_data.get("active_formulas", [])
        }

    except Exception as e:
        logger.error(f"Ошибка генерации прогноза для {user.telegram_id}: {e}")
        return {
            "success": False,
            "error": get_user_error(e)
        }


async def generate_period_forecast(
    user: User,
    period_type: str,
    save_to_db: bool = True
) -> dict:
    """
    Генерация прогноза на период

    Args:
        user: Объект пользователя
        period_type: Тип периода ('3d', 'week', 'month')
        save_to_db: Сохранять ли в БД

    Returns:
        Словарь с данными прогноза
    """
    today = date.today()

    # Определяем период
    period_days = {
        "3d": 3,
        "week": 7,
        "month": 30
    }
    days = period_days.get(period_type, 7)
    end_date = today + timedelta(days=days)

    period_names = {
        "3d": "2-3 дня",
        "week": "неделю",
        "month": "месяц"
    }
    period_name = period_names.get(period_type, period_type)

    if not user.natal_data_complete:
        return {
            "success": False,
            "error": "Натальные данные не заполнены"
        }

    try:
        # Вычисляем смещение часового пояса с учётом даты рождения
        timezone_name = user.birth_tz or "Europe/Moscow"
        timezone_hours = get_timezone_offset(timezone_name, user.birth_date)

        # Собираем транзиты за весь период
        all_transits = []
        key_dates = {}
        all_formulas = []  # Собираем формулы за весь период

        for day_offset in range(days):
            check_date = today + timedelta(days=day_offset)
            forecast_data = generate_full_forecast_data(
                birth_date=user.birth_date,
                birth_time=user.birth_time,
                birth_lat=user.birth_lat,
                birth_lon=user.birth_lon,
                residence_lat=user.residence_lat or user.birth_lat,
                residence_lon=user.residence_lon or user.birth_lon,
                target_date=check_date,
                timezone_hours=timezone_hours
            )

            # Находим важные транзиты (точные аспекты)
            for transit in forecast_data.get("transits", []):
                if transit.get("orb", 10) < 2:  # Точный аспект
                    date_str = check_date.strftime("%d.%m")
                    if date_str not in key_dates:
                        key_dates[date_str] = []
                    key_dates[date_str].append(transit)

            all_transits.extend(forecast_data.get("transits", []))

            # Собираем активные формулы (без дубликатов по ключу)
            for formula in forecast_data.get("active_formulas", []):
                if not any(f["key"] == formula["key"] for f in all_formulas):
                    all_formulas.append(formula)

        # Формируем данные для AI
        transits_text = format_period_transits_for_ai(key_dates, today, end_date)

        # Генерируем прогноз через AI
        ai_response = await generate_forecast(
            transits_data=transits_text,
            transits_list=all_transits,
            user_name=user.display_name,
            forecast_type="period",
            target_date=f"{today.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}"
        )

        if not ai_response:
            return {
                "success": False,
                "error": "Не удалось получить ответ от AI"
            }

        # Сохраняем в БД
        forecast_record = None
        if save_to_db:
            import json
            forecast_record = Forecast.create(
                user=user,
                forecast_type=f"period_{period_type}",
                target_date=today,
                period_end=end_date,
                transits_data=json.dumps({"key_dates": key_dates}, ensure_ascii=False, default=str),
                forecast_text=ai_response
            )

        return {
            "success": True,
            "forecast_id": forecast_record.id if forecast_record else None,
            "text": ai_response,
            "period_name": period_name,
            "date_range": f"{today.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}",
            "key_dates": key_dates
        }

    except Exception as e:
        logger.error(f"Ошибка генерации периодного прогноза для {user.telegram_id}: {e}")
        return {
            "success": False,
            "error": get_user_error(e)
        }


# ============== ФОРМАТИРОВАНИЕ ДЛЯ ПОЛЬЗОВАТЕЛЯ ==============

def format_transits_list(forecast_data: dict) -> str:
    """
    Форматирование списка транзитов для вывода пользователю

    Формат: ПланетаТ аспект ПланетаR   формула
    Где:
    - ПланетаТ — символ транзитной планеты + "т"
    - аспект — символ аспекта (☌, ⚹, □, △, ☍)
    - ПланетаR — символ натальной планеты + "ᴿ" если ретроградная
    - формула — X(дома) +/- Y(дома), где ₀ = соуправление
    """
    # Форматируем дату
    target_date = forecast_data.get("date", "")
    if target_date:
        try:
            dt = datetime.fromisoformat(target_date)
            formatted_date = dt.strftime("%d.%m.%Y")
        except:
            formatted_date = target_date
    else:
        formatted_date = date.today().strftime("%d.%m.%Y")

    lines = [f"<b>📊 Прогноз на {formatted_date}</b>\n"]

    # Символы планет
    planet_symbols = {
        "Солнце": "☉", "Луна": "☽", "Меркурий": "☿", "Венера": "♀",
        "Марс": "♂", "Юпитер": "♃", "Сатурн": "♄", "Уран": "♅",
        "Нептун": "♆", "Плутон": "♇"
    }

    aspects = forecast_data.get("aspects_detailed", [])

    for asp in aspects[:10]:
        # Извлекаем данные
        transit = asp.get("transit", "")
        natal = asp.get("natal", "")
        symbol = asp.get("symbol", "")

        # Формула по управлению (вычислена в astro_engine)
        formula = asp.get("formula", "")

        # Извлекаем имена планет
        t_name = transit.split()[-1] if transit else ""
        n_name = natal.split()[-1] if natal else ""

        # Символы планет
        t_sym = planet_symbols.get(t_name, "?")
        n_sym = planet_symbols.get(n_name, "?")

        # Проверяем ретроградность натальной планеты
        natal_retrograde = ""
        natal_positions = forecast_data.get("natal", {}).get("positions", {})
        if natal_positions.get(n_name, {}).get("retrograde"):
            natal_retrograde = "ᴿ"

        # Проверяем ретроградность транзитной планеты
        transit_retrograde = ""
        transit_positions = forecast_data.get("transits", {}).get("positions", {})
        if transit_positions.get(t_name, {}).get("retrograde"):
            transit_retrograde = "ᴿ"

        # Формируем строку: ☽т ♂ ☽ᴿ   формула
        line = f"<code>{t_sym}{transit_retrograde}т {symbol} {n_sym}{natal_retrograde}   {formula}</code>"
        lines.append(line)

    return "\n".join(lines)


# ============== ФОРМАТИРОВАНИЕ ДЛЯ AI ==============

def format_transits_for_ai(forecast_data: dict) -> str:
    """
    Форматирование транзитов для передачи в AI

    Включает формулу по управлению планет для каждого аспекта.
    Формула показывает какие дома активируются: дома транзитной планеты → дома натальной планеты
    """
    lines = ["АКТИВНЫЕ ТРАНЗИТЫ:"]

    # Используем aspects_detailed
    aspects = forecast_data.get("aspects_detailed", [])

    for asp in aspects[:10]:  # Топ 10 аспектов (уже отсортированы по приоритету)
        transit = asp.get("transit", "")
        natal = asp.get("natal", "")
        aspect_name = asp.get("aspect", "")
        orb = asp.get("orb", 0)
        t_house = asp.get("transit_house", 0)
        n_house = asp.get("natal_house", 0)
        nature = asp.get("nature", "")
        formula = asp.get("formula", "")  # Формула по управлению

        # Извлекаем имена планет
        t_name = transit.split()[-1] if transit else ""
        n_name = natal.split()[-1] if natal else ""

        line = f"• {t_name} {aspect_name} {n_name}, орб {orb:.1f}°"
        line += f"\n  Природа: {nature}"
        line += f"\n  Позиции: тр. в {t_house} доме, нат. в {n_house} доме"
        if formula:
            line += f"\n  Формула: {formula} (дома тр. планеты → дома нат. планеты)"
        lines.append(line)

    # Добавляем положение Луны
    moon_sign = forecast_data.get("moon_sign", "")
    moon_house = forecast_data.get("moon_house", 0)
    if moon_sign:
        lines.append(f"\n🌙 ЛУНА: в {moon_sign}, {moon_house} дом")

    return "\n".join(lines)


def format_period_transits_for_ai(key_dates: dict, start: date, end: date) -> str:
    """Форматирование транзитов периода для AI"""
    lines = [f"КЛЮЧЕВЫЕ ДАТЫ ПЕРИОДА {start.strftime('%d.%m')} - {end.strftime('%d.%m')}:"]

    for date_str, transits in sorted(key_dates.items()):
        lines.append(f"\n📅 {date_str}:")
        for transit in transits[:5]:  # Максимум 5 транзитов на дату
            t_planet = transit.get("transit_planet", "")
            n_planet = transit.get("natal_planet", "")
            aspect = transit.get("aspect", "")
            orb = transit.get("orb", 0)
            lines.append(f"  • {t_planet} {aspect} {n_planet} (орб {orb:.1f}°)")

    return "\n".join(lines)


# ============== ОБРАБОТЧИКИ CALLBACK ==============

async def handle_forecast_today(client: Client, callback: CallbackQuery, user: User):
    """Обработка запроса прогноза на сегодня"""
    await callback.answer("Генерирую прогноз...")

    # Показываем сообщение о генерации
    today = date.today()
    await callback.message.edit_text(
        FORECAST_GENERATING_TEXT.format(date=today.strftime("%d.%m.%Y"))
    )

    # Генерируем прогноз
    result = await generate_daily_forecast(user, today)

    if result["success"]:
        await callback.message.edit_text(
            FORECAST_TEXT.format(
                date=today.strftime("%d.%m.%Y"),
                content=result["text"]
            ),
            reply_markup=get_forecast_keyboard(result.get("forecast_id", 0))
        )
    else:
        await callback.message.edit_text(
            FORECAST_ERROR_TEXT.format(error=result.get("error", "Неизвестная ошибка")),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔮 Главное меню", callback_data="back_main")]
            ])
        )


async def handle_forecast_period(client: Client, callback: CallbackQuery, user: User, period: str):
    """Обработка запроса прогноза на период"""
    period_names = {
        "3d": "2-3 дня",
        "week": "неделю",
        "month": "месяц"
    }

    await callback.answer(f"Генерирую прогноз на {period_names.get(period, period)}...")

    # Показываем сообщение о генерации
    await callback.message.edit_text(
        f"📅 <b>Прогноз на {period_names.get(period, period)}</b>\n\n⏳ Анализирую транзиты за период..."
    )

    # Генерируем прогноз
    result = await generate_period_forecast(user, period)

    if result["success"]:
        await callback.message.edit_text(
            PERIOD_FORECAST_TEXT.format(
                period=result["period_name"],
                date_range=result["date_range"],
                content=result["text"]
            ),
            reply_markup=get_forecast_keyboard(result.get("forecast_id", 0))
        )
    else:
        await callback.message.edit_text(
            FORECAST_ERROR_TEXT.format(error=result.get("error", "Неизвестная ошибка")),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔮 Главное меню", callback_data="back_main")]
            ])
        )


async def handle_forecast_date(client: Client, callback: CallbackQuery, user: User, date_str: str):
    """Обработка запроса прогноза на конкретную дату"""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await callback.answer("Некорректная дата", show_alert=True)
        return

    await callback.answer("Генерирую прогноз...")

    # Показываем сообщение о генерации
    await callback.message.edit_text(
        FORECAST_GENERATING_TEXT.format(date=target_date.strftime("%d.%m.%Y"))
    )

    # Генерируем прогноз
    result = await generate_daily_forecast(user, target_date)

    if result["success"]:
        await callback.message.edit_text(
            FORECAST_TEXT.format(
                date=target_date.strftime("%d.%m.%Y"),
                content=result["text"]
            ),
            reply_markup=get_forecast_keyboard(result.get("forecast_id", 0))
        )
    else:
        await callback.message.edit_text(
            FORECAST_ERROR_TEXT.format(error=result.get("error", "Неизвестная ошибка")),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔮 Главное меню", callback_data="back_main")]
            ])
        )


async def handle_voice_forecast(client: Client, callback: CallbackQuery, forecast_id: int):
    """Озвучивание прогноза с отображением прогресса"""
    await callback.answer()

    # Отправляем сообщение с прогрессом
    progress_msg = await callback.message.reply("🔊 Генерирую аудио...")

    try:
        # Получаем прогноз из БД
        forecast = Forecast.get_by_id(forecast_id)

        # Генерируем голосовое сообщение
        audio_path = await text_to_speech(forecast.forecast_text)

        if audio_path:
            # Обновляем статус
            await progress_msg.edit_text("📤 Отправляю аудио...")

            # Отправляем голосовое
            await callback.message.reply_voice(audio_path)

            # Удаляем сообщение о прогрессе
            await progress_msg.delete()

            # Удаляем временный файл
            import os
            if os.path.exists(audio_path):
                os.remove(audio_path)
        else:
            await progress_msg.edit_text("❌ " + ERROR_MESSAGES["tts_failed"])

    except Forecast.DoesNotExist:
        await progress_msg.edit_text("❌ " + ERROR_MESSAGES["tts_not_found"])
    except Exception as e:
        logger.error(f"Ошибка озвучки прогноза: {e}")
        await progress_msg.edit_text("❌ " + ERROR_MESSAGES["tts_failed"])


# ============== АВТОМАТИЧЕСКАЯ РАССЫЛКА ==============

async def send_daily_forecast(client: Client, user: User):
    """
    Отправка ежедневного прогноза пользователю
    Вызывается планировщиком
    """
    if not user.has_active_subscription():
        logger.info(f"Пропуск рассылки для {user.telegram_id}: нет подписки")
        return False

    if not user.natal_data_complete:
        logger.info(f"Пропуск рассылки для {user.telegram_id}: нет натальных данных")
        return False

    try:
        # Генерируем прогноз
        result = await generate_daily_forecast(user, date.today())

        if not result["success"]:
            logger.error(f"Не удалось сгенерировать прогноз для {user.telegram_id}")
            return False

        # Отправляем сообщение
        await client.send_message(
            user.telegram_id,
            FORECAST_TEXT.format(
                date=date.today().strftime("%d.%m.%Y"),
                content=result["text"]
            ),
            reply_markup=get_forecast_keyboard(result.get("forecast_id", 0))
        )

        logger.info(f"Прогноз отправлен: {user.telegram_id}")
        return True

    except Exception as e:
        logger.error(f"Ошибка отправки прогноза {user.telegram_id}: {e}")
        return False


def register_handlers(app: Client):
    """Регистрация обработчиков прогнозов"""
    # Основные обработчики уже зарегистрированы в start.py
    # Здесь можно добавить дополнительные, если нужно
    pass
