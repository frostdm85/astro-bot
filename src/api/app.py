#!/usr/bin/env python3
# coding: utf-8
"""
FastAPI приложение для Mini App астро-бота
"""

import logging
import re
import hashlib
import hmac
import urllib.parse
from datetime import date, timedelta
from typing import Optional, List, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pathlib import Path

# Импорт расшифровки формул
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from data.formula_meanings import analyze_transit_formula

logger = logging.getLogger(__name__)


# ============== ЧЕЛОВЕКОЧИТАЕМЫЕ ОШИБКИ ==============

API_ERROR_MESSAGES = {
    # Пользователь
    "user_not_found": "Пользователь не найден",
    "natal_incomplete": "Данные рождения не заполнены",

    # Прогнозы
    "forecast_error": "Не удалось получить прогноз. Попробуйте позже.",
    "calendar_error": "Не удалось загрузить календарь. Попробуйте позже.",

    # Валидация
    "invalid_date": "Некорректный формат даты",
    "invalid_time": "Некорректный формат времени",

    # Сервер
    "server_error": "Сервис временно недоступен. Попробуйте через минуту.",
    "timeout_error": "Превышено время ожидания. Попробуйте снова.",
}


def get_api_error(error: Exception) -> str:
    """
    Преобразует техническую ошибку в понятное пользователю сообщение для API
    """
    error_str = str(error).lower()

    if "timeout" in error_str or "timed out" in error_str:
        return API_ERROR_MESSAGES["timeout_error"]
    if "rate limit" in error_str or "too many requests" in error_str:
        return API_ERROR_MESSAGES["server_error"]
    if "connection" in error_str or "network" in error_str:
        return API_ERROR_MESSAGES["server_error"]

    return API_ERROR_MESSAGES["server_error"]


# ============== ЗЛЫЕ/ДОБРЫЕ ПЛАНЕТЫ ==============

# Злые (напряжённые) планеты — соединение с ними даёт негативный аспект
MALEFIC_PLANETS = {'Марс', 'Сатурн', 'Уран', 'Нептун', 'Плутон'}
# Добрые (благоприятные) планеты — соединение с ними даёт позитивный аспект
BENEFIC_PLANETS = {'Солнце', 'Луна', 'Венера', 'Юпитер'}


def is_conjunction_negative(transit_planet: str, natal_planet: str) -> bool:
    """
    Определяет, является ли соединение напряжённым.
    Соединение негативное, если хотя бы одна из планет — злая.
    """
    return transit_planet in MALEFIC_PLANETS or natal_planet in MALEFIC_PLANETS


def determine_aspect_nature(aspect_name: str, transit_planet: str = '', natal_planet: str = '') -> tuple:
    """
    Определяет природу аспекта: nature (positive/negative/neutral) и is_positive (bool).

    Returns:
        (nature: str, is_positive: bool)
    """
    aspect = aspect_name.lower()

    if aspect in ['трин', 'секстиль', 'тригон']:
        return "positive", True
    elif aspect in ['квадратура', 'оппозиция']:
        return "negative", False
    elif aspect in ['соединение', 'conjunction']:
        # Соединение: проверяем злые планеты
        if is_conjunction_negative(transit_planet, natal_planet):
            return "negative", False
        else:
            return "positive", True
    else:
        # Неизвестный аспект — нейтральный
        return "neutral", True


# Путь к статике Mini App
WEBAPP_DIR = Path(__file__).parent.parent / "webapp"

# Создаём FastAPI приложение
app = FastAPI(
    title="Astro Bot API",
    description="API для Mini App астрологического бота",
    version="1.0.0"
)

# CORS для Telegram WebApp - только доверенные домены
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.orionastro.ru",
        "https://t.me",
        "https://web.telegram.org",
        "http://localhost:8080",  # для локальной разработки
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["X-Telegram-Init-Data", "Content-Type", "Authorization"],
)


# ============== МОДЕЛИ ==============

class TransitItem(BaseModel):
    """Один транзит"""
    time: str
    transit_planet: str
    natal_planet: str
    aspect: str
    aspect_symbol: str
    nature: str  # positive, negative, neutral
    formula: str
    meanings: list[str]


class DayForecast(BaseModel):
    """Прогноз на день"""
    date: str
    day_name: str
    transits: list[TransitItem]
    summary: str
    mood: str  # good, neutral, difficult


class CalendarDay(BaseModel):
    """День в календаре"""
    date: str
    mood: str  # good, neutral, difficult
    has_transits: bool
    transit_count: int


class ForecastQuestion(BaseModel):
    """Вопрос по прогнозу"""
    question: str
    date_str: str  # Дата прогноза в формате dd.mm.yyyy
    forecast_context: str = ""  # Контекст прогноза (summary)


class ForecastAnswer(BaseModel):
    """Ответ на вопрос по прогнозу"""
    answer: str


# ============== API ENDPOINTS ==============

@app.get("/api/health")
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "ok", "service": "astro-bot-api"}


@app.get("/api/moon")
async def get_moon_info():
    """
    Получить информацию о текущей фазе Луны.
    Не требует авторизации.
    """
    try:
        from services.astro_engine import get_full_moon_info
        moon_data = get_full_moon_info()
        return moon_data
    except Exception as e:
        logger.error(f"Error getting moon info: {e}")
        raise HTTPException(status_code=500, detail="Ошибка расчёта фазы Луны")


@app.get("/api/retrogrades")
async def get_retrogrades(year: int = None):
    """
    Получить информацию о ретроградных планетах на год.
    Не требует авторизации.
    """
    try:
        from services.astro_engine import get_retrogrades_info
        if year is None:
            from datetime import datetime
            year = datetime.now().year
        retro_data = get_retrogrades_info(year)
        return retro_data
    except Exception as e:
        logger.error(f"Error getting retrogrades info: {e}")
        raise HTTPException(status_code=500, detail="Ошибка расчёта ретроградов")


# ============== ПОЛЬЗОВАТЕЛЬСКИЕ ЭНДПОИНТЫ ==============

from fastapi import Header as FastAPIHeader


class UserSettings(BaseModel):
    """Настройки пользователя"""
    forecast_time: Optional[str] = None
    forecast_enabled: Optional[bool] = None  # Утренний прогноз вкл/выкл
    push_enabled: Optional[bool] = None  # Важные транзиты вкл/выкл


def verify_user_from_header(init_data: str, expected_user_id: int) -> int:
    """
    Проверка что запрос от указанного пользователя.
    Возвращает user_id или выбрасывает HTTPException.
    """
    from config import BOT_TOKEN, ADMIN_ID

    if not init_data:
        raise HTTPException(status_code=401, detail="Authorization required")

    # Проверяем подпись (функция определена ниже в файле)
    try:
        params = dict(urllib.parse.parse_qsl(init_data))
        received_hash = params.pop('hash', None)

        if not received_hash:
            raise HTTPException(status_code=401, detail="Invalid init data")

        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(params.items())
        )

        secret_key = hmac.new(
            b'WebAppData',
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            raise HTTPException(status_code=401, detail="Invalid signature")

        user_data = params.get('user', '{}')
        import json as json_lib
        user = json_lib.loads(user_data)
        user_id = user.get('id')

        if not user_id:
            raise HTTPException(status_code=401, detail="No user id in init data")

        # Разрешаем доступ если это сам пользователь ИЛИ админ
        if user_id != expected_user_id and user_id != ADMIN_ID:
            raise HTTPException(status_code=403, detail="Access denied")

        return user_id

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying user: {e}")
        raise HTTPException(status_code=401, detail="Authorization failed")


def validate_forecast_time(time_str: str) -> bool:
    """Валидация формата времени HH:MM"""
    import re
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
        return False
    return True


@app.get("/api/user/{user_id}/check")
async def check_user(
    user_id: int,
    x_telegram_init_data: str = FastAPIHeader(default="", alias="X-Telegram-Init-Data")
):
    """
    Проверка существования пользователя и наличия натальных данных
    """
    verify_user_from_header(x_telegram_init_data, user_id)

    from database.models import User

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.natal_data_complete:
        raise HTTPException(status_code=400, detail="Natal data not complete")

    return {
        "exists": True,
        "natal_complete": user.natal_data_complete,
        "name": user.display_name
    }


@app.get("/api/user/{user_id}/settings")
async def get_user_settings(
    user_id: int,
    x_telegram_init_data: str = FastAPIHeader(default="", alias="X-Telegram-Init-Data")
):
    """
    Получить настройки пользователя
    """
    verify_user_from_header(x_telegram_init_data, user_id)

    from database.models import User

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "forecast_time": user.forecast_time or "09:00",
        "forecast_enabled": user.push_forecast if hasattr(user, 'push_forecast') else True,
        "push_enabled": user.push_transits if hasattr(user, 'push_transits') else False,
        "user_data": {
            "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
            "birth_time": str(user.birth_time)[:8] if user.birth_time else None,
            "birth_place": user.birth_place,
            "residence": user.residence_place
        }
    }


@app.post("/api/user/{user_id}/settings")
async def update_user_settings(
    user_id: int,
    settings: UserSettings,
    x_telegram_init_data: str = FastAPIHeader(default="", alias="X-Telegram-Init-Data")
):
    """
    Обновить настройки пользователя
    """
    verify_user_from_header(x_telegram_init_data, user_id)

    from database.models import User

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if settings.forecast_time is not None:
        if not validate_forecast_time(settings.forecast_time):
            raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")
        user.forecast_time = settings.forecast_time

    if settings.forecast_enabled is not None:
        user.push_forecast = settings.forecast_enabled

    if settings.push_enabled is not None:
        user.push_transits = settings.push_enabled

    user.save()

    return {"status": "ok"}


# ============== ДЕМО-РЕЖИМ ДЛЯ ТЕСТИРОВАНИЯ ==============

def parse_formula(formula: str) -> Tuple[List[int], List[int], bool]:
    """
    Парсит формулу типа "4(1,8) + 7(2,9)" или "4(1,8) - 10(3,4)"

    Returns:
        (transit_houses, natal_houses, is_positive)
    """
    # Определяем знак аспекта
    is_positive = "+" in formula or "±" in formula

    # Ищем паттерн: число(число,число) или число(число)
    pattern = r'(\d+)\(([^)]+)\)'
    matches = re.findall(pattern, formula)

    if len(matches) >= 2:
        # Первая группа - транзитная планета
        transit_main = int(matches[0][0])
        transit_rulers = [int(x.strip()) for x in matches[0][1].split(',')]
        transit_houses = [transit_main] + transit_rulers

        # Вторая группа - натальная планета
        natal_main = int(matches[1][0])
        natal_rulers = [int(x.strip()) for x in matches[1][1].split(',')]
        natal_houses = [natal_main] + natal_rulers

        return transit_houses, natal_houses, is_positive

    return [], [], is_positive


def get_meanings_from_formula(formula: str) -> List[str]:
    """
    Получает ВСЕ интерпретации для формулы
    """
    transit_houses, natal_houses, is_positive = parse_formula(formula)

    if not transit_houses or not natal_houses:
        return ["Информация о транзите"]

    meanings = analyze_transit_formula(transit_houses, natal_houses, is_positive)

    if not meanings:
        # Если формулы не найдены, даём общее описание
        if is_positive:
            return ["Благоприятное время"]
        else:
            return ["Требует внимательности"]

    return meanings


def get_demo_forecast(target_date: date) -> DayForecast:
    """Демо-прогноз для тестирования интерфейса"""
    day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    # Тестовые транзиты как в Альтаире с реальными формулами
    demo_transit_data = [
        {
            "time": "09:25",
            "transit_planet": "Луна",
            "natal_planet": "Венера",
            "aspect": "секстиль",
            "aspect_symbol": "⚹",
            "nature": "positive",
            "formula": "4(1,8) + 7(2,9)"
        },
        {
            "time": "12:40",
            "transit_planet": "Меркурий",
            "natal_planet": "Юпитер",
            "aspect": "трин",
            "aspect_symbol": "△",
            "nature": "positive",
            "formula": "3(6,9) + 9(2,5)"
        },
        {
            "time": "15:18",
            "transit_planet": "Луна",
            "natal_planet": "Сатурн",
            "aspect": "квадратура",
            "aspect_symbol": "□",
            "nature": "negative",
            "formula": "4(1,8) - 10(3,4)"
        },
        {
            "time": "18:33",
            "transit_planet": "Венера",
            "natal_planet": "Марс",
            "aspect": "соединение",
            "aspect_symbol": "☌",
            "nature": "neutral",
            "formula": "7(2,9) + 1(6,11)"  # Соединение как позитивный
        },
        {
            "time": "21:45",
            "transit_planet": "Луна",
            "natal_planet": "Нептун",
            "aspect": "трин",
            "aspect_symbol": "△",
            "nature": "positive",
            "formula": "4(1,8) + 12(5,10)"
        },
    ]

    # Создаём транзиты с расшифрованными формулами
    demo_transits = []
    for tr in demo_transit_data:
        meanings = get_meanings_from_formula(tr["formula"])
        demo_transits.append(TransitItem(
            time=tr["time"],
            transit_planet=tr["transit_planet"],
            natal_planet=tr["natal_planet"],
            aspect=tr["aspect"],
            aspect_symbol=tr["aspect_symbol"],
            nature=tr["nature"],
            formula=tr["formula"],
            meanings=meanings
        ))

    # Определяем настроение дня
    positive = sum(1 for t in demo_transits if t.nature == "positive")
    negative = sum(1 for t in demo_transits if t.nature == "negative")

    if positive > negative:
        mood = "good"
    elif negative > positive:
        mood = "difficult"
    else:
        mood = "neutral"

    return DayForecast(
        date=target_date.strftime("%d.%m.%Y"),
        day_name=day_names[target_date.weekday()],
        transits=demo_transits,
        summary="До 12:40 хорошее время для общения и переговоров. С 13:18 до 15:18 не лучшее время для важных решений — лучше отложить серьёзные разговоры. Вечером творческое настроение, хорошее время для романтики.",
        mood=mood
    )


@app.get("/api/demo/forecast/today")
async def get_demo_today():
    """Демо-прогноз на сегодня"""
    return get_demo_forecast(date.today())


@app.get("/api/forecast/{user_id}/today")
async def get_today_forecast(user_id: int):
    """
    Получить прогноз на сегодня
    """
    from database.models import User
    from services.astro_engine import calculate_local_natal, calculate_transits, format_transits_text
    from services.groq_client import generate_forecast
    from services.geocoder import get_timezone_offset

    try:
        user = User.get_or_none(User.telegram_id == user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.natal_data_complete:
            raise HTTPException(status_code=400, detail="Natal data not complete")

        today = date.today()
        # TZ для натальной карты (место рождения)
        birth_tz_hours = get_timezone_offset(user.birth_tz or "Europe/Moscow", user.birth_date)
        # TZ для отображения времени транзитов (место проживания)
        display_tz_hours = get_timezone_offset(user.residence_tz or user.birth_tz or "Europe/Moscow", today)

        natal = calculate_local_natal(
            birth_date=user.birth_date,
            birth_time=user.birth_time,
            birth_lat=user.birth_lat,
            birth_lon=user.birth_lon,
            residence_lat=user.residence_lat or user.birth_lat,
            residence_lon=user.residence_lon or user.birth_lon,
            timezone_hours=birth_tz_hours
        )

        transits = calculate_transits(
            natal_data=natal,
            start_date=today,
            days=1,
            residence_lat=user.residence_lat or user.birth_lat,
            residence_lon=user.residence_lon or user.birth_lon,
            timezone_hours=display_tz_hours,
            transit_cusps_tz=display_tz_hours
        )

        # Фильтруем транзиты по времени: оставляем только с 6:00 до 23:55
        from datetime import time as dt_time
        transits_filtered = []
        for tr in transits:
            exact_dt = tr.get('exact_datetime')
            if exact_dt:
                t = exact_dt.time()
                # Включаем транзиты с 06:00 до 23:55
                if dt_time(6, 0) <= t <= dt_time(23, 55):
                    transits_filtered.append(tr)
        transits = transits_filtered if transits_filtered else transits  # fallback если всё отфильтровалось

        transits_text = format_transits_text(transits)

        summary = await generate_forecast(
            transits_data=transits_text,
            transits_list=transits,
            user_name=user.display_name,
            forecast_type="daily"
        )

        transit_items = []
        for tr in transits:
            # Используем функцию для определения природы аспекта с учётом злых планет
            transit_planet = tr.get('transit_planet', '')
            natal_planet = tr.get('natal_planet', '')
            aspect_name = tr.get('aspect_name', '')
            nature, is_positive = determine_aspect_nature(aspect_name, transit_planet, natal_planet)

            transit_houses = [tr.get('transit_house', 0)] + (tr.get('transit_rules', []) or [])
            natal_houses = [tr.get('natal_house', 0)] + (tr.get('natal_rules', []) or [])
            transit_houses = [h for h in transit_houses if h]
            natal_houses = [h for h in natal_houses if h]

            meanings = analyze_transit_formula(transit_houses, natal_houses, is_positive)
            if not meanings:
                meanings = ["Благоприятное время" if is_positive else "Требует внимательности"]

            formula_display = format_formula_display(
                tr.get('transit_house', 0),
                tr.get('transit_rules', []),
                tr.get('natal_house', 0),
                tr.get('natal_rules', []),
                is_positive
            )

            exact_dt = tr.get('exact_datetime')
            time_str = exact_dt.strftime("%H:%M") if exact_dt else ""

            transit_items.append(TransitItem(
                time=time_str,
                transit_planet=tr.get('transit_planet', ''),
                natal_planet=tr.get('natal_planet', ''),
                aspect=aspect_name,
                aspect_symbol=tr.get('aspect_symbol', ''),
                nature=nature,
                formula=formula_display,
                meanings=meanings
            ))

        positive_count = sum(1 for t in transit_items if t.nature == "positive")
        negative_count = sum(1 for t in transit_items if t.nature == "negative")
        if positive_count > negative_count:
            mood = "good"
        elif negative_count > positive_count:
            mood = "difficult"
        else:
            mood = "neutral"

        day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

        # Данные пользователя для отображения
        user_data = {
            "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
            "birth_time": str(user.birth_time)[:8] if user.birth_time else None,
            "birth_place": user.birth_place,
            "residence": user.residence_place
        }

        return {
            "date": today.strftime("%d.%m.%Y"),
            "day_name": day_names[today.weekday()],
            "transits": [t.model_dump() for t in transit_items],
            "summary": summary,
            "mood": mood,
            "user_data": user_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting forecast: {e}")
        raise HTTPException(status_code=500, detail=get_api_error(e))


@app.get("/api/forecast/{user_id}/calendar")
async def get_calendar(
    user_id: int,
    year: int = Query(default=None),
    month: int = Query(default=None),
    force_refresh: bool = Query(default=False)
):
    """
    Получить календарь на месяц с отметками дней.
    Данные кэшируются в БД на 30 дней.
    Дни после окончания подписки помечаются как locked.
    """
    from database.models import User, CalendarCache
    from services.astro_engine import calculate_local_natal, calculate_transits
    from services.geocoder import get_timezone_offset
    from datetime import datetime

    try:
        user = User.get_or_none(User.telegram_id == user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.natal_data_complete:
            raise HTTPException(status_code=400, detail="Natal data not complete")

        # Определяем месяц
        today = date.today()
        if year is None:
            year = today.year
        if month is None:
            month = today.month

        # Получаем дату окончания подписки
        sub = user.get_subscription()
        subscription_end = None
        if sub and sub.expires_at and sub.status in ['active', 'expiring_soon']:
            subscription_end = sub.expires_at.date() if isinstance(sub.expires_at, datetime) else sub.expires_at

        # Проверяем кэш в БД (если не форсированное обновление)
        # Но кэш НЕ используем если подписка изменилась (проверяем по subscription_end)
        if not force_refresh:
            cached = CalendarCache.get_cached(user_id, year, month)
            if cached:
                logger.info(f"Calendar cache hit for user {user_id}, {year}-{month}")
                cached_days = cached.get_days()

                # Обновляем locked статус для кэшированных дней (подписка могла измениться)
                for day in cached_days:
                    day_date = datetime.strptime(day["date"], "%d.%m.%Y").date()
                    # День заблокирован если: в будущем И после окончания подписки
                    if subscription_end and day_date > today and day_date > subscription_end:
                        day["locked"] = True
                        day["mood"] = "locked"
                    else:
                        day["locked"] = False

                return {
                    "year": year,
                    "month": month,
                    "days": cached_days,
                    "subscription_end": subscription_end.strftime("%d.%m.%Y") if subscription_end else None,
                    "from_cache": True
                }

        logger.info(f"Calculating calendar for user {user_id}, {year}-{month}")

        # Первый и последний день месяца
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        days_count = (last_day - first_day).days + 1

        # Определяем до какого дня рассчитывать транзиты
        # Рассчитываем: прошлые дни + дни до конца подписки
        if subscription_end:
            calc_end = min(last_day, subscription_end)
        else:
            # Нет подписки — рассчитываем только прошлые дни + сегодня
            calc_end = today

        # Сколько дней рассчитывать (от первого дня месяца до calc_end)
        calc_days = max(0, (calc_end - first_day).days + 1)

        # TZ для натальной карты (место рождения)
        birth_tz_hours = get_timezone_offset(user.birth_tz or "Europe/Moscow", user.birth_date)
        # TZ для отображения времени транзитов (место проживания)
        display_tz_hours = get_timezone_offset(user.residence_tz or user.birth_tz or "Europe/Moscow", first_day)

        natal = calculate_local_natal(
            birth_date=user.birth_date,
            birth_time=user.birth_time,
            birth_lat=user.birth_lat,
            birth_lon=user.birth_lon,
            residence_lat=user.residence_lat or user.birth_lat,
            residence_lon=user.residence_lon or user.birth_lon,
            timezone_hours=birth_tz_hours  # TZ рождения для натальной карты
        )

        # Рассчитываем транзиты только если есть дни для расчёта
        transits = []
        if calc_days > 0:
            transits = calculate_transits(
                natal_data=natal,
                start_date=first_day,
                days=calc_days,
                residence_lat=user.residence_lat or user.birth_lat,
                residence_lon=user.residence_lon or user.birth_lon,
                timezone_hours=display_tz_hours,  # TZ проживания для отображения
                transit_cusps_tz=display_tz_hours
            )

        # Группируем транзиты по дням
        days_data = {}
        for tr in transits:
            exact_dt = tr.get('exact_datetime')
            if not exact_dt:
                continue
            day_str = exact_dt.strftime("%d.%m.%Y")
            if day_str not in days_data:
                days_data[day_str] = {"positive": 0, "negative": 0, "neutral": 0}

            # Определяем природу аспекта с учётом злых планет
            transit_planet = tr.get('transit_planet', '')
            natal_planet = tr.get('natal_planet', '')
            aspect_name = tr.get('aspect_name', '')
            nature, _ = determine_aspect_nature(aspect_name, transit_planet, natal_planet)

            if nature == "positive":
                days_data[day_str]["positive"] += 1
            elif nature == "negative":
                days_data[day_str]["negative"] += 1
            else:
                days_data[day_str]["neutral"] += 1

        # Формируем ответ для всех дней месяца
        calendar_days = []
        for day_offset in range(days_count):
            current_date = first_day + timedelta(days=day_offset)
            day_str = current_date.strftime("%d.%m.%Y")

            # Проверяем, заблокирован ли день
            is_locked = False
            if subscription_end and current_date > today and current_date > subscription_end:
                is_locked = True
            elif not subscription_end and current_date > today:
                # Нет подписки — будущие дни заблокированы
                is_locked = True

            if is_locked:
                calendar_days.append({
                    "date": day_str,
                    "mood": "locked",
                    "has_transits": False,
                    "transit_count": 0,
                    "locked": True
                })
            else:
                day_info = days_data.get(day_str, {"positive": 0, "negative": 0, "neutral": 0})
                transit_count = day_info["positive"] + day_info["negative"] + day_info["neutral"]

                if day_info["positive"] > day_info["negative"]:
                    mood = "good"
                elif day_info["negative"] > day_info["positive"]:
                    mood = "difficult"
                else:
                    mood = "neutral"

                calendar_days.append({
                    "date": day_str,
                    "mood": mood if transit_count > 0 else "neutral",
                    "has_transits": transit_count > 0,
                    "transit_count": transit_count,
                    "locked": False
                })

        # Сохраняем в кэш БД (TTL 30 дней)
        CalendarCache.save_cache(user_id, year, month, calendar_days, ttl_days=30)
        logger.info(f"Calendar saved to cache for user {user_id}, {year}-{month}")

        return {
            "year": year,
            "month": month,
            "days": calendar_days,
            "subscription_end": subscription_end.strftime("%d.%m.%Y") if subscription_end else None,
            "from_cache": False
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting calendar: {e}")
        raise HTTPException(status_code=500, detail=get_api_error(e))


def format_formula_display(transit_house: int, transit_rules: List[int],
                          natal_house: int, natal_rules: List[int],
                          is_positive: bool) -> str:
    """Форматирует формулу в виде 4(1,8) + 7(2,9)"""
    sign = "+" if is_positive else "-"

    # Транзитная часть
    t_rules_str = ",".join(str(r) for r in transit_rules) if transit_rules else ""
    t_part = f"{transit_house}({t_rules_str})" if t_rules_str else str(transit_house)

    # Натальная часть
    n_rules_str = ",".join(str(r) for r in natal_rules) if natal_rules else ""
    n_part = f"{natal_house}({n_rules_str})" if n_rules_str else str(natal_house)

    return f"{t_part} {sign} {n_part}"


@app.get("/api/forecast/{user_id}/date/{date_str}")
async def get_date_forecast(user_id: int, date_str: str):
    """
    Получить прогноз на конкретную дату
    """
    from datetime import datetime
    from database.models import User
    from services.astro_engine import calculate_local_natal, calculate_transits, format_transits_text
    from services.groq_client import generate_forecast
    from services.geocoder import get_timezone_offset

    try:
        # Парсим дату
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        user = User.get_or_none(User.telegram_id == user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.natal_data_complete:
            raise HTTPException(status_code=400, detail="Natal data not complete")

        # TZ для натальной карты (место рождения)
        birth_tz_hours = get_timezone_offset(user.birth_tz or "Europe/Moscow", user.birth_date)
        # TZ для отображения времени транзитов (место проживания)
        display_tz_hours = get_timezone_offset(user.residence_tz or user.birth_tz or "Europe/Moscow", target_date)

        natal = calculate_local_natal(
            birth_date=user.birth_date,
            birth_time=user.birth_time,
            birth_lat=user.birth_lat,
            birth_lon=user.birth_lon,
            residence_lat=user.residence_lat or user.birth_lat,
            residence_lon=user.residence_lon or user.birth_lon,
            timezone_hours=birth_tz_hours  # TZ рождения для натальной карты
        )

        transits = calculate_transits(
            natal_data=natal,
            start_date=target_date,
            days=1,
            residence_lat=user.residence_lat or user.birth_lat,
            residence_lon=user.residence_lon or user.birth_lon,
            timezone_hours=display_tz_hours,  # TZ проживания для отображения
            transit_cusps_tz=display_tz_hours
        )

        # Фильтруем транзиты по времени: оставляем только с 6:00 до 23:55
        from datetime import time as dt_time
        transits_filtered = []
        for tr in transits:
            exact_dt = tr.get('exact_datetime')
            if exact_dt:
                t = exact_dt.time()
                # Включаем транзиты с 06:00 до 23:55
                if dt_time(6, 0) <= t <= dt_time(23, 55):
                    transits_filtered.append(tr)
        transits = transits_filtered if transits_filtered else transits  # fallback если всё отфильтровалось

        transits_text = format_transits_text(transits)

        summary = await generate_forecast(
            transits_data=transits_text,
            transits_list=transits,
            user_name=user.display_name,
            forecast_type="date",
            target_date=target_date.strftime("%d.%m.%Y")
        )

        transit_items = []
        for tr in transits:
            # Используем функцию для определения природы аспекта с учётом злых планет
            transit_planet = tr.get('transit_planet', '')
            natal_planet = tr.get('natal_planet', '')
            aspect_name = tr.get('aspect_name', '')
            nature, is_positive = determine_aspect_nature(aspect_name, transit_planet, natal_planet)

            # Собираем дома для расшифровки
            transit_houses = [tr.get('transit_house', 0)] + (tr.get('transit_rules', []) or [])
            natal_houses = [tr.get('natal_house', 0)] + (tr.get('natal_rules', []) or [])
            transit_houses = [h for h in transit_houses if h]
            natal_houses = [h for h in natal_houses if h]

            # Расшифровка формул
            meanings = analyze_transit_formula(transit_houses, natal_houses, is_positive)
            if not meanings:
                meanings = ["Благоприятное время" if is_positive else "Требует внимательности"]

            # Формула для отображения
            formula_display = format_formula_display(
                tr.get('transit_house', 0),
                tr.get('transit_rules', []),
                tr.get('natal_house', 0),
                tr.get('natal_rules', []),
                is_positive
            )

            # Время
            exact_dt = tr.get('exact_datetime')
            time_str = exact_dt.strftime("%H:%M") if exact_dt else ""

            transit_items.append(TransitItem(
                time=time_str,
                transit_planet=tr.get('transit_planet', ''),
                natal_planet=tr.get('natal_planet', ''),
                aspect=aspect_name,
                aspect_symbol=tr.get('aspect_symbol', ''),
                nature=nature,
                formula=formula_display,
                meanings=meanings
            ))

        positive_count = sum(1 for t in transit_items if t.nature == "positive")
        negative_count = sum(1 for t in transit_items if t.nature == "negative")
        if positive_count > negative_count:
            mood = "good"
        elif negative_count > positive_count:
            mood = "difficult"
        else:
            mood = "neutral"

        day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

        # Данные пользователя для отображения
        user_data = {
            "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
            "birth_time": str(user.birth_time)[:8] if user.birth_time else None,
            "birth_place": user.birth_place,
            "residence": user.residence_place
        }

        return {
            "date": target_date.strftime("%d.%m.%Y"),
            "day_name": day_names[target_date.weekday()],
            "transits": [t.model_dump() for t in transit_items],
            "summary": summary,
            "mood": mood,
            "user_data": user_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting date forecast: {e}")
        raise HTTPException(status_code=500, detail=get_api_error(e))


# ============== ВОПРОСЫ ПО ПРОГНОЗУ ==============

@app.post("/api/forecast/{user_id}/question", response_model=ForecastAnswer)
async def ask_forecast_question(user_id: int, question_data: ForecastQuestion):
    """
    Задать вопрос по прогнозу на конкретный день.
    AI ответит на основе данных прогноза этого дня.
    """
    try:
        from database.models import User
        from services.groq_client import ask_forecast

        user = User.get_or_none(User.telegram_id == user_id)
        if not user:
            raise HTTPException(status_code=404, detail=API_ERROR_MESSAGES["user_not_found"])

        if not question_data.question.strip():
            raise HTTPException(status_code=400, detail="Вопрос не может быть пустым")

        # Генерируем ответ на вопрос
        answer = await ask_forecast(
            question=question_data.question,
            date_str=question_data.date_str,
            forecast_context=question_data.forecast_context,
            user_name=user.first_name or ""
        )

        return ForecastAnswer(answer=answer)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error answering forecast question: {e}")
        raise HTTPException(status_code=500, detail=get_api_error(e))


# ============== СТАТИКА MINI APP ==============

# Монтируем статику
if WEBAPP_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEBAPP_DIR)), name="static")


@app.get("/webapp")
async def webapp_index():
    """Главная страница Mini App"""
    index_path = WEBAPP_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    raise HTTPException(status_code=404, detail="Mini App not found")


@app.get("/webapp/{path:path}")
async def webapp_files(path: str):
    """Файлы Mini App"""
    file_path = WEBAPP_DIR / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    raise HTTPException(status_code=404, detail="File not found")


# ============== ADMIN API ==============

from config import ADMIN_ID

# Простая проверка админа по ID из заголовка
def verify_admin(admin_id: int = Query(..., alias="admin_id")):
    """Проверка прав администратора"""
    if admin_id != ADMIN_ID:
        raise HTTPException(status_code=403, detail="Access denied")
    return admin_id


class AdminUserUpdate(BaseModel):
    """Модель обновления пользователя админом"""
    first_name: Optional[str] = None
    birth_date: Optional[str] = None  # DD.MM.YYYY
    birth_time: Optional[str] = None  # HH:MM
    birth_place: Optional[str] = None
    birth_lat: Optional[float] = None
    birth_lon: Optional[float] = None
    birth_tz: Optional[str] = None
    residence_place: Optional[str] = None
    residence_lat: Optional[float] = None
    residence_lon: Optional[float] = None
    residence_tz: Optional[str] = None
    is_admin: Optional[bool] = None
    natal_data_complete: Optional[bool] = None


class AdminSubscriptionCreate(BaseModel):
    """Создание/продление подписки"""
    days: int = 30


@app.get("/api/admin/stats")
async def admin_stats(admin_id: int = Query(...)):
    """Статистика для админ-панели"""
    verify_admin(admin_id)

    from database.models import get_stats
    return get_stats()


@app.get("/api/admin/users")
async def admin_users_list(
    admin_id: int = Query(...),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    filter_type: Optional[str] = Query(default=None)  # all, with_data, without_data, with_subscription
):
    """Список пользователей с пагинацией и фильтрацией"""
    verify_admin(admin_id)

    from database.models import User, Subscription
    from datetime import datetime

    query = User.select()

    # Фильтрация
    if filter_type == "with_data":
        query = query.where(User.natal_data_complete == True)
    elif filter_type == "without_data":
        query = query.where(User.natal_data_complete == False)
    elif filter_type == "with_subscription":
        # Пользователи с активной подпиской
        active_sub_users = (
            Subscription.select(Subscription.user)
            .where(
                Subscription.status.in_(['active', 'expiring_soon']),
                Subscription.expires_at > datetime.now()
            )
        )
        query = query.where(User.telegram_id.in_(active_sub_users))

    # Поиск
    if search:
        search_term = f"%{search}%"
        query = query.where(
            (User.first_name.contains(search)) |
            (User.username.contains(search)) |
            (User.telegram_id == int(search) if search.isdigit() else False)
        )

    # Подсчёт общего количества
    total = query.count()

    # Пагинация
    offset = (page - 1) * limit
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit)

    users_list = []
    for user in users:
        sub = user.get_subscription()
        users_list.append({
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
            "birth_place": user.birth_place,
            "natal_data_complete": user.natal_data_complete,
            "is_admin": user.is_admin,
            "subscription_status": sub.status if sub else None,
            "subscription_expires": sub.expires_at.strftime("%d.%m.%Y") if sub and sub.expires_at else None,
            "created_at": user.created_at.strftime("%d.%m.%Y %H:%M")
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "users": users_list
    }


@app.get("/api/admin/user/{user_id}")
async def admin_get_user(user_id: int, admin_id: int = Query(...)):
    """Получить полные данные пользователя"""
    verify_admin(admin_id)

    from database.models import User

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub = user.get_subscription()

    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
        "birth_time": str(user.birth_time)[:8] if user.birth_time else None,
        "birth_place": user.birth_place,
        "birth_lat": user.birth_lat,
        "birth_lon": user.birth_lon,
        "birth_tz": user.birth_tz,
        "residence_place": user.residence_place,
        "residence_lat": user.residence_lat,
        "residence_lon": user.residence_lon,
        "residence_tz": user.residence_tz,
        "forecast_time": user.forecast_time,
        "push_transits": user.push_transits,
        "is_admin": user.is_admin,
        "natal_data_complete": user.natal_data_complete,
        "questions_today": user.questions_today,
        "subscription": {
            "status": sub.status,
            "started_at": sub.started_at.strftime("%d.%m.%Y") if sub and sub.started_at else None,
            "expires_at": sub.expires_at.strftime("%d.%m.%Y %H:%M") if sub and sub.expires_at else None,
            "days_left": sub.days_left if sub else 0
        } if sub else None,
        "created_at": user.created_at.strftime("%d.%m.%Y %H:%M"),
        "updated_at": user.updated_at.strftime("%d.%m.%Y %H:%M")
    }


@app.put("/api/admin/user/{user_id}")
async def admin_update_user(user_id: int, data: AdminUserUpdate, admin_id: int = Query(...)):
    """Обновить данные пользователя"""
    verify_admin(admin_id)

    from database.models import User, CalendarCache
    from datetime import datetime

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Флаг: изменились ли данные, влияющие на расчёт прогноза
    natal_data_changed = False

    # Обновляем поля
    if data.first_name is not None:
        user.first_name = data.first_name

    if data.birth_date is not None:
        try:
            user.birth_date = datetime.strptime(data.birth_date, "%d.%m.%Y").date()
            natal_data_changed = True
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth_date format. Use DD.MM.YYYY")

    if data.birth_time is not None:
        try:
            user.birth_time = datetime.strptime(data.birth_time, "%H:%M").time()
            natal_data_changed = True
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth_time format. Use HH:MM")

    if data.birth_place is not None:
        user.birth_place = data.birth_place
    if data.birth_lat is not None:
        user.birth_lat = data.birth_lat
        natal_data_changed = True
    if data.birth_lon is not None:
        user.birth_lon = data.birth_lon
        natal_data_changed = True
    if data.birth_tz is not None:
        user.birth_tz = data.birth_tz
        natal_data_changed = True

    if data.residence_place is not None:
        user.residence_place = data.residence_place
    if data.residence_lat is not None:
        user.residence_lat = data.residence_lat
        natal_data_changed = True
    if data.residence_lon is not None:
        user.residence_lon = data.residence_lon
        natal_data_changed = True
    if data.residence_tz is not None:
        user.residence_tz = data.residence_tz
        natal_data_changed = True

    if data.is_admin is not None:
        user.is_admin = data.is_admin

    if data.natal_data_complete is not None:
        user.natal_data_complete = data.natal_data_complete

    # Автоматически проверяем полноту натальных данных
    if user.has_natal_data() and not user.natal_data_complete:
        user.natal_data_complete = True

    user.save()

    # Если изменились натальные данные или место проживания — инвалидируем кэш прогнозов
    if natal_data_changed:
        deleted_cache = CalendarCache.invalidate_for_user(user_id)
        logger.info(f"Натальные данные изменены для user {user_id}, кэш инвалидирован ({deleted_cache} записей)")
        return {"status": "ok", "message": f"User updated, calendar cache invalidated ({deleted_cache} entries)"}

    return {"status": "ok", "message": "User updated"}


@app.post("/api/admin/user/{user_id}/subscription")
async def admin_manage_subscription(user_id: int, data: AdminSubscriptionCreate, admin_id: int = Query(...)):
    """Создать или продлить подписку"""
    verify_admin(admin_id)

    from database.models import User, Subscription

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Проверяем есть ли активная подписка
    existing_sub = user.get_subscription()

    if existing_sub and existing_sub.status in ['active', 'expiring_soon']:
        # Продлеваем существующую
        existing_sub.activate(days=data.days)
        return {"status": "ok", "message": f"Subscription extended by {data.days} days"}
    else:
        # Создаём новую
        new_sub = Subscription.create_for_user(user)
        new_sub.activate(days=data.days)
        return {"status": "ok", "message": f"Subscription created for {data.days} days"}


@app.delete("/api/admin/user/{user_id}/subscription")
async def admin_cancel_subscription(user_id: int, admin_id: int = Query(...)):
    """Отменить подписку"""
    verify_admin(admin_id)

    from database.models import User

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub = user.get_subscription()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")

    sub.cancel()
    return {"status": "ok", "message": "Subscription cancelled"}


@app.post("/api/admin/recalculate")
async def admin_recalculate_cache(
    admin_id: int = Query(...),
    user_id: Optional[int] = Query(default=None)
):
    """
    Полный сброс всех прогнозов.

    - Без user_id: очистить ВСЕ данные ВСЕХ пользователей
    - С user_id: очистить данные конкретного пользователя

    Очищаются:
    - CalendarCache (кэш календаря)
    - Forecast (сгенерированные AI прогнозы)

    После сброса прогнозы пересчитаются при следующем запросе.
    """
    verify_admin(admin_id)

    from database.models import CalendarCache, Forecast, User

    if user_id:
        # Очистка данных конкретного пользователя
        user = User.get_or_none(User.telegram_id == user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        deleted_cache = CalendarCache.invalidate_for_user(user_id)
        deleted_forecasts = Forecast.delete().where(Forecast.user == user).execute()

        logger.info(f"Admin {admin_id} reset data for user {user_id}: cache={deleted_cache}, forecasts={deleted_forecasts}")
        return {
            "status": "ok",
            "message": f"Данные пользователя {user_id} сброшены",
            "deleted_cache": deleted_cache,
            "deleted_forecasts": deleted_forecasts
        }
    else:
        # Очистка ВСЕХ данных ВСЕХ пользователей
        deleted_cache = CalendarCache.delete().execute()
        deleted_forecasts = Forecast.delete().execute()

        logger.info(f"Admin {admin_id} reset ALL data: cache={deleted_cache}, forecasts={deleted_forecasts}")
        return {
            "status": "ok",
            "message": "Все прогнозы сброшены",
            "deleted_cache": deleted_cache,
            "deleted_forecasts": deleted_forecasts
        }


@app.get("/api/admin/subscriptions")
async def admin_subscriptions_list(
    admin_id: int = Query(...),
    status: Optional[str] = Query(default=None)  # active, expiring_soon, expired, pending
):
    """Список подписок"""
    verify_admin(admin_id)

    from database.models import Subscription, User

    query = Subscription.select(Subscription, User).join(User)

    if status:
        query = query.where(Subscription.status == status)

    subscriptions = []
    for sub in query.order_by(Subscription.created_at.desc()).limit(100):
        subscriptions.append({
            "id": sub.id,
            "user_id": sub.user.telegram_id,
            "username": sub.user.username,
            "first_name": sub.user.first_name,
            "status": sub.status,
            "started_at": sub.started_at.strftime("%d.%m.%Y") if sub.started_at else None,
            "expires_at": sub.expires_at.strftime("%d.%m.%Y %H:%M") if sub.expires_at else None,
            "days_left": sub.days_left,
            "amount": float(sub.amount) if sub.amount else None
        })

    return {"subscriptions": subscriptions}


# ============== ADMIN WEBAPP ==============

ADMIN_DIR = Path(__file__).parent.parent / "webapp"

@app.get("/admin")
async def admin_index():
    """Админ-панель"""
    admin_path = ADMIN_DIR / "admin.html"
    if admin_path.exists():
        return FileResponse(str(admin_path))
    raise HTTPException(status_code=404, detail="Admin panel not found")


# ============== ADMIN API (совместимый с admin-webapp HTML) ==============
# Эти эндпоинты используют X-Telegram-Init-Data для авторизации

import hashlib
import hmac
import urllib.parse
import json as json_module

def verify_telegram_init_data(init_data: str, bot_token: str) -> dict:
    """
    Проверка подписи Telegram initData по документации.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        return None

    try:
        # Парсим параметры
        params = dict(urllib.parse.parse_qsl(init_data))
        received_hash = params.pop('hash', None)

        if not received_hash:
            return None

        # Создаём строку для проверки (сортированные параметры)
        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(params.items())
        )

        # Создаём секретный ключ
        secret_key = hmac.new(
            b'WebAppData',
            bot_token.encode(),
            hashlib.sha256
        ).digest()

        # Вычисляем хеш
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        # Сравниваем
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # Парсим user data
        user_data = params.get('user', '{}')
        return json_module.loads(user_data)

    except Exception as e:
        logger.error(f"Error verifying init_data: {e}")
        return None


def verify_admin_from_header(init_data: str) -> int:
    """
    Проверка админа через X-Telegram-Init-Data заголовок.
    Возвращает user_id админа или выбрасывает HTTPException.
    """
    from config import BOT_TOKEN

    if not init_data:
        raise HTTPException(status_code=401, detail="Authorization required: X-Telegram-Init-Data header missing")

    # Проверяем подпись
    user = verify_telegram_init_data(init_data, BOT_TOKEN)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired init data")

    user_id = user.get('id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid init data: no user id")

    if user_id != ADMIN_ID:
        raise HTTPException(status_code=403, detail="Access denied: not admin")

    return user_id


from fastapi import Header, Request


@app.get("/api/stats")
async def webapp_admin_stats(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    """Статистика для админ-панели (webapp)"""
    verify_admin_from_header(x_telegram_init_data)
    from database.models import get_stats
    return get_stats()


class GeoSearchRequest(BaseModel):
    """Запрос поиска города"""
    city: str


class GeoSearchResult(BaseModel):
    """Результат поиска города"""
    city: str
    country: str
    lat: float
    lon: float
    coords_formatted: str
    timezone: str


@app.post("/api/geocode/search")
async def webapp_geocode_search(
    data: GeoSearchRequest,
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")
):
    """Поиск города для автокомплита"""
    verify_admin_from_header(x_telegram_init_data)

    from services.geocoder import search_cities, format_coordinates

    try:
        geo_results = search_cities(data.city, limit=5)
        results = []
        for geo in geo_results:
            results.append({
                "city": geo.city,
                "country": geo.country,
                "lat": geo.latitude,
                "lon": geo.longitude,
                "coords_formatted": format_coordinates(geo.latitude, geo.longitude),
                "timezone": geo.timezone
            })
        return {"results": results}
    except Exception as e:
        logger.error(f"Geocode search error: {e}")
        return {"results": []}


@app.get("/api/users")
async def webapp_admin_users_list(
    filter: str = Query(default="all"),
    search: str = Query(default=""),
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")
):
    """Список пользователей для админ-панели (webapp)"""
    verify_admin_from_header(x_telegram_init_data)

    from database.models import User, Subscription
    from datetime import datetime, timedelta

    query = User.select()

    # Фильтрация по статусу
    if filter == "active":
        # Активная подписка
        now = datetime.now()
        active_users = (
            Subscription.select(Subscription.user)
            .where(
                Subscription.status.in_(['active', 'expiring_soon']),
                Subscription.expires_at > now
            )
        )
        query = query.where(User.telegram_id.in_(active_users))
    elif filter == "expiring":
        # Истекающая в течение 7 дней
        now = datetime.now()
        week_later = now + timedelta(days=7)
        expiring_users = (
            Subscription.select(Subscription.user)
            .where(
                Subscription.expires_at > now,
                Subscription.expires_at <= week_later
            )
        )
        query = query.where(User.telegram_id.in_(expiring_users))
    elif filter == "expired":
        # Истёкшая подписка
        now = datetime.now()
        expired_users = (
            Subscription.select(Subscription.user)
            .where(Subscription.expires_at <= now)
        )
        query = query.where(User.telegram_id.in_(expired_users))
    elif filter == "nodata":
        # Без натальных данных
        query = query.where(User.natal_data_complete == False)

    # Поиск
    if search:
        query = query.where(
            (User.first_name.contains(search)) |
            (User.username.contains(search)) |
            (User.telegram_id == int(search) if search.isdigit() else False)
        )

    users_list = []
    for user in query.order_by(User.created_at.desc()).limit(100):
        sub = user.get_subscription()

        # Вычисляем days_left
        days_left = 0
        if sub and sub.expires_at:
            from datetime import datetime
            delta = sub.expires_at - datetime.now()
            days_left = max(0, delta.days)

        users_list.append({
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
            "birth_time": str(user.birth_time)[:8] if user.birth_time else None,
            "birth_place": user.birth_place,
            "birth_lat": user.birth_lat,
            "birth_lon": user.birth_lon,
            "birth_tz": user.birth_tz,
            "residence_place": user.residence_place,
            "natal_data_complete": user.natal_data_complete,
            "subscription": {
                "status": sub.status if sub else None,
                "expires_at": sub.expires_at.strftime("%d.%m.%Y") if sub and sub.expires_at else None,
                "days_left": days_left
            } if sub else None
        })

    return {"users": users_list}


@app.get("/api/users/{user_id}")
async def webapp_admin_get_user(
    user_id: int,
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")
):
    """Получить детали пользователя для админ-панели"""
    verify_admin_from_header(x_telegram_init_data)

    from database.models import User
    from services.geocoder import get_timezone_offset

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub = user.get_subscription()

    # Вычисляем UTC offset для timezone
    birth_tz_offset = None
    if user.birth_tz:
        try:
            from datetime import date as date_type
            birth_tz_offset = get_timezone_offset(user.birth_tz, date_type.today())
        except:
            pass

    # Вычисляем days_left
    days_left = 0
    if sub and sub.expires_at:
        from datetime import datetime
        delta = sub.expires_at - datetime.now()
        days_left = max(0, delta.days)

    # Получаем статистику
    from database.models import Forecast
    forecasts_count = Forecast.select().where(Forecast.user == user).count() if hasattr(user, 'forecasts') else 0

    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
        "birth_time": str(user.birth_time)[:8] if user.birth_time else None,
        "birth_place": user.birth_place,
        "birth_lat": user.birth_lat,
        "birth_lon": user.birth_lon,
        "birth_tz": user.birth_tz,
        "birth_tz_offset": birth_tz_offset,
        "residence_place": user.residence_place,
        "residence_lat": user.residence_lat,
        "residence_lon": user.residence_lon,
        "residence_tz": user.residence_tz,
        "natal_data_complete": user.natal_data_complete,
        "questions_today": user.questions_today,
        "forecasts_count": forecasts_count,
        "subscription": {
            "status": sub.status if sub else None,
            "expires_at": sub.expires_at.strftime("%d.%m.%Y") if sub and sub.expires_at else None,
            "days_left": days_left
        } if sub else None
    }


class WebappUserUpdate(BaseModel):
    """Обновление данных пользователя из webapp"""
    telegram_id: Optional[int] = None
    first_name: Optional[str] = None
    birth_date: Optional[str] = None  # DD.MM.YYYY
    birth_time: Optional[str] = None  # HH:MM:SS
    birth_place: Optional[str] = None
    birth_lat: Optional[float] = None
    birth_lon: Optional[float] = None
    birth_tz: Optional[str] = None
    residence_place: Optional[str] = None
    residence_lat: Optional[float] = None
    residence_lon: Optional[float] = None
    residence_tz: Optional[str] = None


@app.patch("/api/users/{user_id}")
async def webapp_admin_update_user(
    user_id: int,
    data: WebappUserUpdate,
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")
):
    """Обновить данные пользователя"""
    verify_admin_from_header(x_telegram_init_data)

    from database.models import User, CalendarCache
    from datetime import datetime

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Отслеживаем изменение натальных данных для инвалидации кэша
    natal_data_changed = False

    # Обновляем поля
    if data.first_name is not None:
        user.first_name = data.first_name

    if data.birth_date is not None:
        try:
            user.birth_date = datetime.strptime(data.birth_date, "%d.%m.%Y").date()
            natal_data_changed = True
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth_date format")

    if data.birth_time is not None:
        try:
            user.birth_time = datetime.strptime(data.birth_time, "%H:%M:%S").time()
            natal_data_changed = True
        except ValueError:
            try:
                user.birth_time = datetime.strptime(data.birth_time, "%H:%M").time()
                natal_data_changed = True
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid birth_time format")

    if data.birth_place is not None:
        user.birth_place = data.birth_place
    if data.birth_lat is not None:
        user.birth_lat = data.birth_lat
        natal_data_changed = True
    if data.birth_lon is not None:
        user.birth_lon = data.birth_lon
        natal_data_changed = True
    if data.birth_tz is not None:
        user.birth_tz = data.birth_tz
        natal_data_changed = True

    if data.residence_place is not None:
        user.residence_place = data.residence_place
    if data.residence_lat is not None:
        user.residence_lat = data.residence_lat
        natal_data_changed = True
    if data.residence_lon is not None:
        user.residence_lon = data.residence_lon
        natal_data_changed = True
    if data.residence_tz is not None:
        user.residence_tz = data.residence_tz
        natal_data_changed = True

    # Проверяем полноту данных
    if user.has_natal_data():
        user.natal_data_complete = True

    user.save()

    # Инвалидируем кэш календаря при изменении натальных данных
    if natal_data_changed:
        deleted_cache = CalendarCache.invalidate_for_user(user_id)
        logger.info(f"Натальные данные изменены для user {user_id}, кэш инвалидирован ({deleted_cache} записей)")
        return {"status": "ok", "cache_invalidated": deleted_cache}

    return {"status": "ok"}


@app.post("/api/users")
async def webapp_admin_create_user(
    data: WebappUserUpdate,
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")
):
    """Создать нового пользователя"""
    verify_admin_from_header(x_telegram_init_data)

    from database.models import User
    from datetime import datetime

    if not data.telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id is required")

    # Проверяем что пользователь не существует
    existing = User.get_or_none(User.telegram_id == data.telegram_id)
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    # Создаём пользователя
    user = User.create(
        telegram_id=data.telegram_id,
        first_name=data.first_name or "User",
        username=None
    )

    # Устанавливаем данные
    if data.birth_date:
        try:
            user.birth_date = datetime.strptime(data.birth_date, "%d.%m.%Y").date()
        except ValueError:
            pass

    if data.birth_time:
        try:
            user.birth_time = datetime.strptime(data.birth_time, "%H:%M:%S").time()
        except ValueError:
            try:
                user.birth_time = datetime.strptime(data.birth_time, "%H:%M").time()
            except ValueError:
                pass

    if data.birth_place:
        user.birth_place = data.birth_place
    if data.birth_lat:
        user.birth_lat = data.birth_lat
    if data.birth_lon:
        user.birth_lon = data.birth_lon
    if data.birth_tz:
        user.birth_tz = data.birth_tz

    if data.residence_place:
        user.residence_place = data.residence_place
    if data.residence_lat:
        user.residence_lat = data.residence_lat
    if data.residence_lon:
        user.residence_lon = data.residence_lon
    if data.residence_tz:
        user.residence_tz = data.residence_tz

    # Проверяем полноту данных
    if user.has_natal_data():
        user.natal_data_complete = True

    user.save()

    return {"status": "ok", "telegram_id": user.telegram_id}


@app.delete("/api/users/{user_id}")
async def webapp_admin_delete_user(
    user_id: int,
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")
):
    """Удалить пользователя"""
    verify_admin_from_header(x_telegram_init_data)

    from database.models import User, Subscription

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Удаляем связанные подписки
    Subscription.delete().where(Subscription.user == user).execute()

    # Удаляем пользователя
    user.delete_instance()

    return {"status": "ok"}


class WebappSubscriptionAction(BaseModel):
    """Действие с подпиской"""
    action: str  # extend, cancel
    days: int = 30


@app.post("/api/users/{user_id}/subscription")
async def webapp_admin_subscription(
    user_id: int,
    data: WebappSubscriptionAction,
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")
):
    """Управление подпиской пользователя"""
    verify_admin_from_header(x_telegram_init_data)

    from database.models import User, Subscription

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.action == "extend":
        # Получаем или создаём подписку
        sub = user.get_subscription()
        if not sub:
            sub = Subscription.create_for_user(user)

        # Продлеваем
        sub.activate(days=data.days)

        return {
            "status": "ok",
            "expires_at": sub.expires_at.strftime("%d.%m.%Y")
        }
    elif data.action == "cancel":
        sub = user.get_subscription()
        if sub:
            sub.cancel()
        return {"status": "ok"}
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
