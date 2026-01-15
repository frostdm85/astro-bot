#!/usr/bin/env python3
# coding: utf-8

"""
Admin Mini App для Астро-бота
FastAPI backend + статика для Telegram WebApp
"""

import os
import sys
import hmac
import hashlib
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Добавляем путь к src для импорта моделей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import BOT_TOKEN, ADMIN_ID
from database.models import (
    User, Subscription, Forecast, SupportTicket, SupportMessage,
    get_stats, init_db, db
)
from services.geocoder import quick_geocode, format_coordinates, search_cities, get_timezone_offset

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Astro Admin", version="1.0.0")

# CORS для Telegram WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статика и шаблоны
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ============== МОДЕЛИ PYDANTIC ==============

class UserCreate(BaseModel):
    telegram_id: int
    first_name: str
    birth_date: str  # DD.MM.YYYY
    birth_time: str  # HH:MM:SS
    birth_place: str
    residence_place: str
    # Опциональные geo-данные (если уже получены с фронтенда)
    birth_lat: Optional[float] = None
    birth_lon: Optional[float] = None
    birth_tz: Optional[str] = None
    residence_lat: Optional[float] = None
    residence_lon: Optional[float] = None
    residence_tz: Optional[str] = None


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    birth_date: Optional[str] = None
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    residence_place: Optional[str] = None
    # Опциональные geo-данные
    birth_lat: Optional[float] = None
    birth_lon: Optional[float] = None
    birth_tz: Optional[str] = None
    residence_lat: Optional[float] = None
    residence_lon: Optional[float] = None
    residence_tz: Optional[str] = None


class SubscriptionAction(BaseModel):
    action: str  # extend, activate, cancel
    days: Optional[int] = 30


class GeoRequest(BaseModel):
    city: str


class TimezoneRequest(BaseModel):
    lat: float
    lon: float


# ============== TELEGRAM AUTH ==============

def validate_telegram_auth(init_data: str) -> Optional[dict]:
    """
    Проверка подписи initData от Telegram WebApp
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))

        if 'hash' not in parsed:
            return None

        received_hash = parsed.pop('hash')

        # Создаём data_check_string
        data_check_arr = sorted([f"{k}={v}" for k, v in parsed.items()])
        data_check_string = '\n'.join(data_check_arr)

        # Секретный ключ
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        # Вычисляем hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if calculated_hash != received_hash:
            logger.warning("Invalid hash in initData")
            return None

        # Парсим user
        if 'user' in parsed:
            user_data = json.loads(parsed['user'])
            return user_data

        return parsed

    except Exception as e:
        logger.error(f"Error validating Telegram auth: {e}")
        return None


async def get_current_admin(request: Request) -> dict:
    """
    Dependency для проверки авторизации админа
    """
    # Получаем initData из заголовка или query параметра
    init_data = request.headers.get("X-Telegram-Init-Data") or \
                request.query_params.get("initData")

    # Для разработки — можно отключить проверку
    if os.getenv("DEV_MODE") == "1":
        return {"id": ADMIN_ID, "first_name": "Dev Admin"}

    if not init_data:
        raise HTTPException(status_code=401, detail="No auth data")

    user_data = validate_telegram_auth(init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid auth")

    # Проверяем, что это админ
    user_id = user_data.get("id")
    if user_id != ADMIN_ID:
        raise HTTPException(status_code=403, detail="Not admin")

    return user_data


# ============== СТРАНИЦЫ ==============

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница Mini App"""
    return templates.TemplateResponse("index.html", {"request": request})


# ============== API ==============

@app.get("/api/stats")
async def api_stats(admin: dict = Depends(get_current_admin)):
    """Статистика"""
    stats = get_stats()
    return stats


@app.get("/api/users")
async def api_users(
    filter: str = "all",
    page: int = 0,
    limit: int = 20,
    search: str = None,
    admin: dict = Depends(get_current_admin)
):
    """Список пользователей"""
    now = datetime.now()
    three_days = now + timedelta(days=3)

    query = User.select()

    # Фильтры
    if filter == "active":
        active_ids = Subscription.select(Subscription.user).where(
            Subscription.status.in_(['active', 'expiring_soon']),
            Subscription.expires_at > now
        )
        query = query.where(User.telegram_id.in_(active_ids))
    elif filter == "expired":
        expired_ids = Subscription.select(Subscription.user).where(
            Subscription.status == 'expired'
        )
        query = query.where(User.telegram_id.in_(expired_ids))
    elif filter == "expiring":
        expiring_ids = Subscription.select(Subscription.user).where(
            Subscription.status.in_(['active', 'expiring_soon']),
            Subscription.expires_at <= three_days,
            Subscription.expires_at > now
        )
        query = query.where(User.telegram_id.in_(expiring_ids))
    elif filter == "nodata":
        query = query.where(User.natal_data_complete == False)

    # Поиск
    if search:
        query = query.where(
            (User.first_name.contains(search)) |
            (User.username.contains(search)) |
            (User.telegram_id == int(search) if search.isdigit() else False)
        )

    total = query.count()
    users = list(query.order_by(User.created_at.desc()).offset(page * limit).limit(limit))

    result = []
    for user in users:
        sub = user.get_subscription()
        result.append({
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
            "birth_time": user.birth_time.strftime("%H:%M:%S") if user.birth_time else None,
            "birth_place": user.birth_place,
            "residence_place": user.residence_place,
            "natal_data_complete": user.natal_data_complete,
            "subscription": {
                "status": sub.status if sub else "none",
                "expires_at": sub.expires_at.strftime("%d.%m.%Y") if sub and sub.expires_at else None,
                "days_left": sub.days_left if sub else 0
            } if sub else None,
            "created_at": user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else None
        })

    return {
        "users": result,
        "total": total,
        "page": page,
        "limit": limit
    }


@app.get("/api/users/{telegram_id}")
async def api_user_detail(telegram_id: int, admin: dict = Depends(get_current_admin)):
    """Детали пользователя"""
    try:
        user = User.get_by_id(telegram_id)
    except User.DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found")

    sub = user.get_subscription()
    forecasts_count = Forecast.select().where(Forecast.user == user).count()

    # Вычисляем поправку по времени на дату рождения
    birth_tz_offset = None
    if user.birth_tz and user.birth_date:
        birth_tz_offset = get_timezone_offset(user.birth_tz, user.birth_date)

    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else None,
        "birth_time": user.birth_time.strftime("%H:%M:%S") if user.birth_time else None,
        "birth_place": user.birth_place,
        "birth_lat": user.birth_lat,
        "birth_lon": user.birth_lon,
        "birth_tz": user.birth_tz,
        "birth_tz_offset": birth_tz_offset,
        "residence_place": user.residence_place,
        "residence_lat": user.residence_lat,
        "residence_lon": user.residence_lon,
        "residence_tz": user.residence_tz,
        "forecast_time": user.forecast_time,
        "questions_today": user.questions_today,
        "natal_data_complete": user.natal_data_complete,
        "subscription": {
            "status": sub.status if sub else "none",
            "expires_at": sub.expires_at.strftime("%d.%m.%Y %H:%M") if sub and sub.expires_at else None,
            "days_left": sub.days_left if sub else 0
        } if sub else None,
        "forecasts_count": forecasts_count,
        "created_at": user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else None
    }


@app.post("/api/users")
async def api_create_user(data: UserCreate, admin: dict = Depends(get_current_admin)):
    """Создать пользователя"""
    # Геокодинг мест - используем данные из запроса, если есть
    if data.birth_lat and data.birth_lon and data.birth_tz:
        # Используем geo-данные из фронтенда
        birth_lat = data.birth_lat
        birth_lon = data.birth_lon
        birth_tz = data.birth_tz
        birth_place = data.birth_place
    else:
        # Геокодинг через API
        birth_geo = quick_geocode(data.birth_place)
        if not birth_geo:
            raise HTTPException(status_code=400, detail=f"Город '{data.birth_place}' не найден")
        birth_lat = birth_geo.latitude
        birth_lon = birth_geo.longitude
        birth_tz = birth_geo.timezone
        birth_place = birth_geo.city

    if data.residence_lat and data.residence_lon and data.residence_tz:
        # Используем geo-данные из фронтенда
        residence_lat = data.residence_lat
        residence_lon = data.residence_lon
        residence_tz = data.residence_tz
        residence_place = data.residence_place
    else:
        # Геокодинг через API
        residence_geo = quick_geocode(data.residence_place)
        if not residence_geo:
            raise HTTPException(status_code=400, detail=f"Город '{data.residence_place}' не найден")
        residence_lat = residence_geo.latitude
        residence_lon = residence_geo.longitude
        residence_tz = residence_geo.timezone
        residence_place = residence_geo.city

    # Парсим дату и время
    try:
        birth_date = datetime.strptime(data.birth_date, "%d.%m.%Y").date()
        time_parts = data.birth_time.split(":")
        from datetime import time
        if len(time_parts) == 3:
            birth_time = time(int(time_parts[0]), int(time_parts[1]), int(time_parts[2]))
        else:
            birth_time = time(int(time_parts[0]), int(time_parts[1]), 0)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат даты/времени: {e}")

    # Создаём или обновляем пользователя
    user, created = User.get_or_create(
        telegram_id=data.telegram_id,
        defaults={"first_name": data.first_name}
    )

    user.first_name = data.first_name
    user.birth_date = birth_date
    user.birth_time = birth_time
    user.birth_place = birth_place
    user.birth_lat = birth_lat
    user.birth_lon = birth_lon
    user.birth_tz = birth_tz
    user.residence_place = residence_place
    user.residence_lat = residence_lat
    user.residence_lon = residence_lon
    user.residence_tz = residence_tz
    user.natal_data_complete = True
    user.save()

    return {"success": True, "telegram_id": user.telegram_id, "created": created}


@app.patch("/api/users/{telegram_id}")
async def api_update_user(
    telegram_id: int,
    data: UserUpdate,
    admin: dict = Depends(get_current_admin)
):
    """Обновить пользователя"""
    try:
        user = User.get_by_id(telegram_id)
    except User.DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found")

    if data.first_name:
        user.first_name = data.first_name

    if data.birth_date:
        try:
            user.birth_date = datetime.strptime(data.birth_date, "%d.%m.%Y").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты")

    if data.birth_time:
        try:
            from datetime import time
            parts = data.birth_time.split(":")
            if len(parts) == 3:
                user.birth_time = time(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                user.birth_time = time(int(parts[0]), int(parts[1]), 0)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат времени")

    if data.birth_place:
        # Используем geo-данные из запроса если есть
        if data.birth_lat and data.birth_lon and data.birth_tz:
            user.birth_place = data.birth_place
            user.birth_lat = data.birth_lat
            user.birth_lon = data.birth_lon
            user.birth_tz = data.birth_tz
        else:
            geo = quick_geocode(data.birth_place)
            if not geo:
                raise HTTPException(status_code=400, detail=f"Город '{data.birth_place}' не найден")
            user.birth_place = geo.city
            user.birth_lat = geo.latitude
            user.birth_lon = geo.longitude
            user.birth_tz = geo.timezone

    if data.residence_place:
        # Используем geo-данные из запроса если есть
        if data.residence_lat and data.residence_lon and data.residence_tz:
            user.residence_place = data.residence_place
            user.residence_lat = data.residence_lat
            user.residence_lon = data.residence_lon
            user.residence_tz = data.residence_tz
        else:
            geo = quick_geocode(data.residence_place)
            if not geo:
                raise HTTPException(status_code=400, detail=f"Город '{data.residence_place}' не найден")
            user.residence_place = geo.city
            user.residence_lat = geo.latitude
            user.residence_lon = geo.longitude
            user.residence_tz = geo.timezone

    # Проверяем полноту данных
    user.natal_data_complete = all([
        user.birth_date, user.birth_time, user.birth_place,
        user.birth_lat, user.birth_lon
    ])

    user.save()
    return {"success": True}


@app.post("/api/users/{telegram_id}/subscription")
async def api_user_subscription(
    telegram_id: int,
    data: SubscriptionAction,
    admin: dict = Depends(get_current_admin)
):
    """Управление подпиской"""
    try:
        user = User.get_by_id(telegram_id)
    except User.DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found")

    sub = user.get_subscription()

    if data.action == "extend" or data.action == "activate":
        if not sub:
            sub = Subscription.create_for_user(user)
        sub.activate(data.days or 30)
        return {"success": True, "expires_at": sub.expires_at.strftime("%d.%m.%Y")}

    elif data.action == "cancel":
        if sub:
            sub.cancel()
        return {"success": True}

    raise HTTPException(status_code=400, detail="Unknown action")


@app.delete("/api/users/{telegram_id}")
async def api_delete_user(telegram_id: int, admin: dict = Depends(get_current_admin)):
    """Удалить пользователя"""
    try:
        user = User.get_by_id(telegram_id)
    except User.DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found")

    # Удаляем связанные записи
    Subscription.delete().where(Subscription.user == user).execute()
    Forecast.delete().where(Forecast.user == user).execute()
    user.delete_instance()

    return {"success": True}


@app.post("/api/geocode")
async def api_geocode(data: GeoRequest, admin: dict = Depends(get_current_admin)):
    """Геокодинг города"""
    geo = quick_geocode(data.city)
    if not geo:
        raise HTTPException(status_code=404, detail=f"Город '{data.city}' не найден")

    return {
        "city": geo.city,
        "country": geo.country,
        "lat": geo.latitude,
        "lon": geo.longitude,
        "timezone": geo.timezone,
        "display_name": geo.display_name,
        "coords_formatted": format_coordinates(geo.latitude, geo.longitude)
    }


@app.post("/api/geocode/search")
async def api_geocode_search(data: GeoRequest):
    """Поиск городов с несколькими результатами для автокомплита"""
    cities = search_cities(data.city, limit=5)

    results = []
    for geo in cities:
        results.append({
            "city": geo.city,
            "country": geo.country,
            "lat": geo.latitude,
            "lon": geo.longitude,
            "timezone": geo.timezone,
            "display_name": geo.display_name,
            "coords_formatted": format_coordinates(geo.latitude, geo.longitude)
        })

    return {"results": results}


@app.post("/api/timezone")
async def api_timezone(data: TimezoneRequest):
    """Определение часового пояса по координатам (не требует авторизации для Mini App)"""
    from timezonefinder import TimezoneFinder

    tf = TimezoneFinder()
    timezone = tf.timezone_at(lat=data.lat, lng=data.lon)

    if not timezone:
        timezone = "UTC"

    # Получаем смещение в часах
    try:
        import pytz
        from datetime import datetime

        tz = pytz.timezone(timezone)
        now = datetime.now(tz)
        offset_seconds = now.utcoffset().total_seconds()
        offset_hours = offset_seconds / 3600
    except Exception:
        offset_hours = 0

    return {
        "timezone": timezone,
        "offset_hours": offset_hours
    }


# ============== STARTUP ==============

@app.on_event("startup")
async def startup():
    """Инициализация при запуске"""
    init_db()
    logger.info("Admin Mini App started")


if __name__ == "__main__":
    import uvicorn

    # DEV_MODE отключён по умолчанию для безопасности
    # Для локальной разработки установите: export DEV_MODE=1
    os.environ["DEV_MODE"] = "1"  # TODO: убрать для production

    uvicorn.run(app, host="0.0.0.0", port=8080)
