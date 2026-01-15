#!/usr/bin/env python3
# coding: utf-8

"""
Сервис геокодинга городов
Использует geopy + timezonefinder для определения координат и часовых поясов
"""

import logging
import ssl
import certifi
from typing import Optional, Tuple
from dataclasses import dataclass

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from timezonefinder import TimezoneFinder

logger = logging.getLogger(__name__)

# SSL контекст для macOS
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Инициализация геокодера с SSL
geolocator = Nominatim(user_agent="astro_bot_geocoder", ssl_context=ssl_context)
tf = TimezoneFinder()


@dataclass
class GeoLocation:
    """Результат геокодинга"""
    city: str               # Название города
    country: str            # Страна
    latitude: float         # Широта
    longitude: float        # Долгота
    timezone: str           # Часовой пояс (например, "Europe/Moscow")
    display_name: str       # Полное название для отображения


def geocode_city(city_name: str, country: str = None) -> Optional[GeoLocation]:
    """
    Найти координаты города

    Args:
        city_name: Название города
        country: Страна (опционально, для уточнения)

    Returns:
        GeoLocation или None если город не найден
    """
    try:
        # Формируем запрос
        query = city_name
        if country:
            query = f"{city_name}, {country}"

        # Геокодинг
        location = geolocator.geocode(
            query,
            language="ru",
            timeout=10
        )

        if not location:
            logger.warning(f"Город не найден: {query}")
            return None

        lat = location.latitude
        lon = location.longitude

        # Определяем часовой пояс
        timezone = tf.timezone_at(lat=lat, lng=lon) or "UTC"

        # Парсим название
        address_parts = location.address.split(", ")
        city = address_parts[0] if address_parts else city_name
        country_name = address_parts[-1] if len(address_parts) > 1 else ""

        return GeoLocation(
            city=city,
            country=country_name,
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            timezone=timezone,
            display_name=location.address
        )

    except GeocoderTimedOut:
        logger.error(f"Таймаут геокодинга для: {city_name}")
        return None
    except GeocoderServiceError as e:
        logger.error(f"Ошибка сервиса геокодинга: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка геокодинга: {e}")
        return None


def get_timezone_offset(timezone_name: str, target_date: 'date' = None) -> float:
    """
    Получить смещение часового пояса в часах для конкретной даты.

    ВАЖНО: Для астрологических расчётов необходимо передавать дату рождения,
    так как часовые пояса менялись в истории (летнее время, декретное время и т.д.)

    Args:
        timezone_name: Название часового пояса (например, "Europe/Moscow")
        target_date: Дата для расчёта (если None - используется текущая дата)

    Returns:
        Смещение в часах от UTC
    """
    try:
        import pytz
        from datetime import datetime, date, time

        tz = pytz.timezone(timezone_name)

        if target_date is None:
            # Используем текущую дату
            dt = datetime.now(tz)
        else:
            # Создаём datetime для указанной даты (полдень для избежания DST переходов)
            if isinstance(target_date, date) and not isinstance(target_date, datetime):
                dt = datetime.combine(target_date, time(12, 0, 0))
            else:
                dt = target_date

            # Локализуем в указанном часовом поясе
            dt = tz.localize(dt)

        offset_seconds = dt.utcoffset().total_seconds()
        return offset_seconds / 3600

    except Exception as e:
        logger.error(f"Ошибка определения смещения для {timezone_name} на дату {target_date}: {e}")
        return 3.0  # MSK по умолчанию


def reverse_geocode(lat: float, lon: float) -> Optional[GeoLocation]:
    """
    Обратный геокодинг: координаты -> город

    Args:
        lat: Широта
        lon: Долгота

    Returns:
        GeoLocation или None
    """
    try:
        location = geolocator.reverse(
            (lat, lon),
            language="ru",
            timeout=10
        )

        if not location:
            return None

        # Определяем часовой пояс
        timezone = tf.timezone_at(lat=lat, lng=lon) or "UTC"

        address = location.raw.get("address", {})
        city = (
            address.get("city") or
            address.get("town") or
            address.get("village") or
            address.get("municipality") or
            "Неизвестно"
        )
        country = address.get("country", "")

        return GeoLocation(
            city=city,
            country=country,
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            timezone=timezone,
            display_name=location.address
        )

    except Exception as e:
        logger.error(f"Ошибка обратного геокодинга: {e}")
        return None


def format_coordinates(lat: float, lon: float) -> str:
    """
    Форматировать координаты для отображения

    Args:
        lat: Широта
        lon: Долгота

    Returns:
        Строка вида "55.7558°N, 37.6173°E"
    """
    lat_dir = "N" if lat >= 0 else "S"
    lon_dir = "E" if lon >= 0 else "W"

    return f"{abs(lat):.4f}°{lat_dir}, {abs(lon):.4f}°{lon_dir}"


# Популярные города для быстрого доступа (кэш)
POPULAR_CITIES = {
    "москва": GeoLocation("Москва", "Россия", 55.7558, 37.6173, "Europe/Moscow", "Москва, Россия"),
    "санкт-петербург": GeoLocation("Санкт-Петербург", "Россия", 59.9343, 30.3351, "Europe/Moscow", "Санкт-Петербург, Россия"),
    "новосибирск": GeoLocation("Новосибирск", "Россия", 55.0084, 82.9357, "Asia/Novosibirsk", "Новосибирск, Россия"),
    "екатеринбург": GeoLocation("Екатеринбург", "Россия", 56.8389, 60.6057, "Asia/Yekaterinburg", "Екатеринбург, Россия"),
    "казань": GeoLocation("Казань", "Россия", 55.7887, 49.1221, "Europe/Moscow", "Казань, Россия"),
    "нижний новгород": GeoLocation("Нижний Новгород", "Россия", 56.2965, 43.9361, "Europe/Moscow", "Нижний Новгород, Россия"),
    "краснодар": GeoLocation("Краснодар", "Россия", 45.0355, 38.9753, "Europe/Moscow", "Краснодар, Россия"),
    "сочи": GeoLocation("Сочи", "Россия", 43.6028, 39.7342, "Europe/Moscow", "Сочи, Россия"),
    "киев": GeoLocation("Киев", "Украина", 50.4501, 30.5234, "Europe/Kiev", "Киев, Украина"),
    "минск": GeoLocation("Минск", "Беларусь", 53.9045, 27.5615, "Europe/Minsk", "Минск, Беларусь"),
}


def quick_geocode(city_name: str) -> Optional[GeoLocation]:
    """
    Быстрый геокодинг с использованием кэша популярных городов

    Args:
        city_name: Название города

    Returns:
        GeoLocation или None
    """
    # Проверяем кэш
    normalized = city_name.lower().strip()
    if normalized in POPULAR_CITIES:
        return POPULAR_CITIES[normalized]

    # Иначе делаем полный запрос
    return geocode_city(city_name)


def search_cities(query: str, limit: int = 5) -> list:
    """
    Поиск городов с несколькими результатами для автокомплита

    Args:
        query: Поисковый запрос
        limit: Максимальное количество результатов

    Returns:
        Список GeoLocation
    """
    results = []
    normalized = query.lower().strip()

    # Сначала ищем в кэше популярных городов
    for key, geo in POPULAR_CITIES.items():
        if normalized in key or key.startswith(normalized):
            results.append(geo)
            if len(results) >= limit:
                return results

    # Если мало результатов — запрос к Nominatim
    if len(results) < limit:
        try:
            locations = geolocator.geocode(
                query,
                language="ru",
                timeout=10,
                exactly_one=False,
                limit=limit - len(results)
            )

            if locations:
                for loc in locations:
                    lat = loc.latitude
                    lon = loc.longitude
                    timezone = tf.timezone_at(lat=lat, lng=lon) or "UTC"

                    address_parts = loc.address.split(", ")
                    city = address_parts[0] if address_parts else query
                    country = address_parts[-1] if len(address_parts) > 1 else ""

                    results.append(GeoLocation(
                        city=city,
                        country=country,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        timezone=timezone,
                        display_name=loc.address
                    ))

        except Exception as e:
            logger.error(f"Ошибка поиска городов: {e}")

    return results
