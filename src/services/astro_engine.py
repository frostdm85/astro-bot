#!/usr/bin/env python3
# coding: utf-8

"""
Астрологический движок на основе Swiss Ephemeris (pyswisseph)
Документация: Context7 /astrorigin/pyswisseph

Расчёт транзитов, аспектов, положений планет
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import swisseph as swe

logger = logging.getLogger(__name__)

# Инициализация Swiss Ephemeris
# Путь к эфемеридам (если есть локальные файлы)
# swe.set_ephe_path("/path/to/ephe")

# Планеты (основные)
PLANETS = {
    swe.SUN: ("Солнце", "☉"),
    swe.MOON: ("Луна", "☽"),
    swe.MERCURY: ("Меркурий", "☿"),
    swe.VENUS: ("Венера", "♀"),
    swe.MARS: ("Марс", "♂"),
    swe.JUPITER: ("Юпитер", "♃"),
    swe.SATURN: ("Сатурн", "♄"),
    swe.URANUS: ("Уран", "♅"),
    swe.NEPTUNE: ("Нептун", "♆"),
    swe.PLUTO: ("Плутон", "♇"),
}

# Специальные точки (Лилит, Узлы)
# По Шестопалову используется MEAN NODE (средний узел)
SPECIAL_POINTS = {
    swe.MEAN_NODE: ("Северный узел", "☊"),
    swe.MEAN_APOG: ("Лилит", "⚸"),
}

# Все объекты для расчёта
PLANETS_ALL = {**PLANETS, **SPECIAL_POINTS}

# Аспекты и их орбисы
ASPECTS = {
    0: ("Соединение", "☌", 8),      # орбис 8°
    60: ("Секстиль", "⚹", 6),
    90: ("Квадратура", "□", 8),
    120: ("Тригон", "△", 8),
    180: ("Оппозиция", "☍", 8),
}

# Знаки зодиака
ZODIAC_SIGNS = [
    ("Овен", "♈"), ("Телец", "♉"), ("Близнецы", "♊"),
    ("Рак", "♋"), ("Лев", "♌"), ("Дева", "♍"),
    ("Весы", "♎"), ("Скорпион", "♏"), ("Стрелец", "♐"),
    ("Козерог", "♑"), ("Водолей", "♒"), ("Рыбы", "♓")
]


@dataclass
class PlanetPosition:
    """Позиция планеты"""
    planet_id: int
    name: str
    symbol: str
    longitude: float        # Долгота в градусах
    latitude: float         # Широта
    distance: float         # Расстояние
    speed: float            # Скорость (градусы/день)
    sign: str               # Знак зодиака
    sign_symbol: str
    degree_in_sign: float   # Градус в знаке
    is_retrograde: bool     # Ретроградность


@dataclass
class Aspect:
    """Аспект между планетами"""
    planet1: str
    planet2: str
    aspect_name: str
    aspect_symbol: str
    exact_angle: float      # Точный угол
    orb: float              # Орбис (отклонение)
    applying: bool          # Сходящийся или расходящийся


def datetime_to_julian(dt: datetime, timezone_hours: float = 0) -> float:
    """
    Конвертация datetime в Julian Day

    Args:
        dt: Дата и время
        timezone_hours: Смещение часового пояса в часах

    Returns:
        Julian Day number
    """
    # Переводим в UT (Universal Time)
    hour_decimal = dt.hour + dt.minute / 60.0 + dt.second / 3600.0 - timezone_hours

    year = dt.year
    month = dt.month
    day = dt.day

    # Корректируем если hour_decimal вышел за пределы суток
    while hour_decimal < 0:
        hour_decimal += 24
        day -= 1
        if day < 1:
            month -= 1
            if month < 1:
                month = 12
                year -= 1
            # Определяем количество дней в предыдущем месяце
            if month in [1, 3, 5, 7, 8, 10, 12]:
                day = 31
            elif month in [4, 6, 9, 11]:
                day = 30
            elif month == 2:
                if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
                    day = 29
                else:
                    day = 28

    while hour_decimal >= 24:
        hour_decimal -= 24
        day += 1
        # Определяем количество дней в текущем месяце
        if month in [1, 3, 5, 7, 8, 10, 12]:
            days_in_month = 31
        elif month in [4, 6, 9, 11]:
            days_in_month = 30
        elif month == 2:
            if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
                days_in_month = 29
            else:
                days_in_month = 28
        if day > days_in_month:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1

    jd = swe.julday(
        year,
        month,
        day,
        hour_decimal,
        swe.GREG_CAL
    )
    return jd


def get_planet_position(planet_id: int, jd: float) -> PlanetPosition:
    """
    Получить позицию планеты на заданный момент

    Args:
        planet_id: ID планеты (swe.SUN, swe.MOON, etc.)
        jd: Julian Day

    Returns:
        PlanetPosition с данными о положении
    """
    # Флаги: используем Swiss Ephemeris + скорость
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED

    # Расчёт позиции
    result, retflags = swe.calc_ut(jd, planet_id, flags)

    longitude = result[0]   # Эклиптическая долгота
    latitude = result[1]    # Эклиптическая широта
    distance = result[2]    # Расстояние в AU
    speed = result[3]       # Скорость в градусах/день

    # Определяем знак зодиака
    sign_index = int(longitude / 30)
    sign_name, sign_symbol = ZODIAC_SIGNS[sign_index]
    degree_in_sign = longitude % 30

    # Имя и символ планеты
    name, symbol = PLANETS.get(planet_id, (f"Planet_{planet_id}", "?"))

    return PlanetPosition(
        planet_id=planet_id,
        name=name,
        symbol=symbol,
        longitude=longitude,
        latitude=latitude,
        distance=distance,
        speed=speed,
        sign=sign_name,
        sign_symbol=sign_symbol,
        degree_in_sign=degree_in_sign,
        is_retrograde=speed < 0
    )


def get_natal_chart(
    birth_date: date,
    birth_time: str,
    birth_lat: float,
    birth_lon: float,
    timezone_hours: float = 3.0  # MSK по умолчанию
) -> Dict[int, PlanetPosition]:
    """
    Рассчитать натальную карту

    Args:
        birth_date: Дата рождения
        birth_time: Время рождения (HH:MM)
        birth_lat: Широта места рождения
        birth_lon: Долгота места рождения
        timezone_hours: Смещение часового пояса

    Returns:
        Словарь {planet_id: PlanetPosition}
    """
    # Парсим время (может быть строка или datetime.time)
    if hasattr(birth_time, 'hour'):
        # datetime.time объект
        hour = birth_time.hour
        minute = birth_time.minute
    else:
        # Строка "HH:MM" или "HH:MM:SS"
        time_parts = str(birth_time).split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0

    dt = datetime(
        birth_date.year,
        birth_date.month,
        birth_date.day,
        hour,
        minute
    )

    jd = datetime_to_julian(dt, timezone_hours)

    natal = {}
    for planet_id in PLANETS.keys():
        natal[planet_id] = get_planet_position(planet_id, jd)

    return natal


def get_transits(
    transit_date: datetime,
    timezone_hours: float = 3.0
) -> Dict[int, PlanetPosition]:
    """
    Получить текущие транзиты на дату

    Args:
        transit_date: Дата транзита
        timezone_hours: Смещение часового пояса

    Returns:
        Словарь {planet_id: PlanetPosition}
    """
    jd = datetime_to_julian(transit_date, timezone_hours)

    transits = {}
    for planet_id in PLANETS.keys():
        transits[planet_id] = get_planet_position(planet_id, jd)

    return transits


def calculate_aspect(pos1: float, pos2: float) -> Optional[Tuple[str, str, float, float]]:
    """
    Проверить наличие аспекта между двумя позициями

    Args:
        pos1: Долгота первой планеты
        pos2: Долгота второй планеты

    Returns:
        (aspect_name, aspect_symbol, exact_angle, orb) или None
    """
    # Вычисляем угол между планетами
    diff = abs(pos1 - pos2)
    if diff > 180:
        diff = 360 - diff

    # Проверяем каждый аспект
    for aspect_angle, (name, symbol, max_orb) in ASPECTS.items():
        orb = abs(diff - aspect_angle)
        if orb <= max_orb:
            return (name, symbol, aspect_angle, orb)

    return None


def get_transit_aspects(
    natal: Dict[int, PlanetPosition],
    transits: Dict[int, PlanetPosition]
) -> List[Aspect]:
    """
    Найти аспекты между транзитными и натальными планетами

    Args:
        natal: Натальные позиции планет
        transits: Транзитные позиции планет

    Returns:
        Список аспектов
    """
    aspects = []

    for t_id, t_pos in transits.items():
        for n_id, n_pos in natal.items():
            aspect_data = calculate_aspect(t_pos.longitude, n_pos.longitude)

            if aspect_data:
                name, symbol, exact_angle, orb = aspect_data

                # Определяем, сходящийся ли аспект
                applying = t_pos.speed > 0  # Упрощённо

                aspects.append(Aspect(
                    planet1=f"{t_pos.symbol} тр. {t_pos.name}",
                    planet2=f"{n_pos.symbol} нат. {n_pos.name}",
                    aspect_name=name,
                    aspect_symbol=symbol,
                    exact_angle=exact_angle,
                    orb=round(orb, 2),
                    applying=applying
                ))

    # Сортируем по точности (меньший орбис = сильнее)
    aspects.sort(key=lambda a: a.orb)

    return aspects


def generate_transits_data(
    birth_date: date,
    birth_time: str,
    birth_lat: float,
    birth_lon: float,
    target_date: date = None,
    timezone_hours: float = 3.0
) -> Dict:
    """
    Сгенерировать полные данные о транзитах для AI

    Args:
        birth_date: Дата рождения
        birth_time: Время рождения
        birth_lat: Широта рождения
        birth_lon: Долгота рождения
        target_date: Дата прогноза (по умолчанию сегодня)
        timezone_hours: Часовой пояс

    Returns:
        Словарь с данными для передачи в Groq
    """
    if target_date is None:
        target_date = date.today()

    target_datetime = datetime.combine(target_date, datetime.now().time())

    # Рассчитываем натал и транзиты
    natal = get_natal_chart(birth_date, birth_time, birth_lat, birth_lon, timezone_hours)
    transits = get_transits(target_datetime, timezone_hours)

    # Находим аспекты
    aspects = get_transit_aspects(natal, transits)

    # Формируем данные
    data = {
        "date": target_date.isoformat(),
        "natal_positions": {},
        "transit_positions": {},
        "aspects": []
    }

    for planet_id, pos in natal.items():
        data["natal_positions"][pos.name] = {
            "sign": pos.sign,
            "degree": round(pos.degree_in_sign, 1),
            "retrograde": pos.is_retrograde
        }

    for planet_id, pos in transits.items():
        data["transit_positions"][pos.name] = {
            "sign": pos.sign,
            "degree": round(pos.degree_in_sign, 1),
            "retrograde": pos.is_retrograde
        }

    for aspect in aspects[:15]:  # Топ-15 аспектов
        data["aspects"].append({
            "transit": aspect.planet1,
            "natal": aspect.planet2,
            "aspect": f"{aspect.aspect_name} ({aspect.aspect_symbol})",
            "orb": aspect.orb,
            "applying": aspect.applying
        })

    return data


def get_moon_phase(jd: float) -> str:
    """Определить фазу Луны"""
    sun_pos = get_planet_position(swe.SUN, jd)
    moon_pos = get_planet_position(swe.MOON, jd)

    diff = (moon_pos.longitude - sun_pos.longitude) % 360

    if diff < 45:
        return "Новолуние"
    elif diff < 90:
        return "Растущий серп"
    elif diff < 135:
        return "Первая четверть"
    elif diff < 180:
        return "Растущая Луна"
    elif diff < 225:
        return "Полнолуние"
    elif diff < 270:
        return "Убывающая Луна"
    elif diff < 315:
        return "Последняя четверть"
    else:
        return "Убывающий серп"


# ============== РАСЧЁТ ДОМОВ ==============

@dataclass
class Houses:
    """Куспиды домов"""
    cusps: List[float]      # 12 куспидов
    asc: float              # Асцендент
    mc: float               # Середина Неба
    house_system: str       # Система домов


def calculate_houses(
    jd: float,
    lat: float,
    lon: float,
    house_system: str = 'K'  # Koch по умолчанию (как в Альтаир)
) -> Houses:
    """
    Рассчитать куспиды домов

    Args:
        jd: Julian Day
        lat: Широта
        lon: Долгота
        house_system: Система домов ('P' - Placidus, 'K' - Koch, 'E' - Equal)

    Returns:
        Houses с куспидами
    """
    # Расчёт домов
    cusps, ascmc = swe.houses(jd, lat, lon, house_system.encode())

    return Houses(
        cusps=list(cusps),
        asc=ascmc[0],
        mc=ascmc[1],
        house_system=house_system
    )


def get_planet_house(longitude: float, cusps: List[float]) -> int:
    """
    Определить, в каком доме находится планета

    Args:
        longitude: Долгота планеты
        cusps: Список куспидов (12 штук)

    Returns:
        Номер дома (1-12)
    """
    for i in range(12):
        next_i = (i + 1) % 12
        cusp1 = cusps[i]
        cusp2 = cusps[next_i]

        # Обработка перехода через 0°
        if cusp2 < cusp1:
            if longitude >= cusp1 or longitude < cusp2:
                return i + 1
        else:
            if cusp1 <= longitude < cusp2:
                return i + 1

    return 1  # По умолчанию


# ============== УПРАВЛЕНИЕ ДОМАМИ ПО ШЕСТОПАЛОВУ ==============

# Управители знаков (прямые планеты)
SIGN_RULERS = {
    'Овен': 'Плутон', 'Телец': 'Венера', 'Близнецы': 'Меркурий',
    'Рак': 'Луна', 'Лев': 'Солнце', 'Дева': 'Меркурий',
    'Весы': 'Венера', 'Скорпион': 'Марс', 'Стрелец': 'Юпитер',
    'Козерог': 'Сатурн', 'Водолей': 'Уран', 'Рыбы': 'Нептун',
}

# Соуправители для ретроградных планет
SIGN_RULERS_RETRO = {
    'Овен': 'Марс', 'Скорпион': 'Плутон', 'Стрелец': 'Нептун',
    'Козерог': 'Уран', 'Водолей': 'Сатурн', 'Рыбы': 'Юпитер',
}

# Знаки планет
PLANET_SIGNS = {
    'Солнце': ['Лев'], 'Луна': ['Рак'],
    'Меркурий': ['Близнецы', 'Дева'], 'Венера': ['Телец', 'Весы'],
    'Марс': ['Скорпион'], 'Юпитер': ['Стрелец'],
    'Сатурн': ['Козерог'], 'Уран': ['Водолей'],
    'Нептун': ['Рыбы'], 'Плутон': ['Овен'],
}

# Дополнительные знаки для ретро-планет
PLANET_SIGNS_RETRO = {
    'Марс': 'Овен', 'Юпитер': 'Рыбы', 'Сатурн': 'Водолей',
    'Уран': 'Козерог', 'Нептун': 'Стрелец', 'Плутон': 'Скорпион',
}


def get_planet_ruled_houses(
    planet_name: str,
    cusps: List[float],
    is_retrograde: bool = False,
    retro_planets: set = None
) -> List[int]:
    """
    Получить список домов, которыми управляет планета по правилам Шестопалова.

    Правила:
    1. Знак на куспиде → УПРАВЛЯЕТ
    2. Включённый знак → СОУПРАВЛЯЕТ
    3. Знак входит >13.5° → СОУПРАВЛЯЕТ
    4. Знак занимает >50% дома → СОУПРАВЛЯЕТ
    5. Ретро-планета управляет обоими знаками

    Args:
        planet_name: Имя планеты
        cusps: Список куспидов (12 штук)
        is_retrograde: Планета ретроградна?
        retro_planets: Множество ретроградных планет

    Returns:
        Список номеров домов (1-12)
    """
    if retro_planets is None:
        retro_planets = set()

    # Знаки планеты
    signs = list(PLANET_SIGNS.get(planet_name, []))

    # Ретро-планета управляет вторым знаком
    if is_retrograde and planet_name in PLANET_SIGNS_RETRO:
        extra = PLANET_SIGNS_RETRO[planet_name]
        if extra not in signs:
            signs.append(extra)

    # Специальные точки
    if planet_name == 'Лилит':
        return [8]  # Лилит всегда связана с VIII домом
    if planet_name == 'Северный узел':
        return []   # Узел не управляет знаками

    ruled_houses = set()

    for house_num in range(1, 13):
        cusp_start = cusps[house_num - 1]
        cusp_end = cusps[house_num % 12]

        # Размер дома
        if cusp_end < cusp_start:
            house_size = (360 - cusp_start) + cusp_end
        else:
            house_size = cusp_end - cusp_start

        # Знак на куспиде
        cusp_sign_idx = int(cusp_start / 30)
        cusp_sign = ZODIAC_SIGNS[cusp_sign_idx][0]
        cusp_deg = cusp_start % 30
        deg_in_cusp_sign = 30 - cusp_deg

        # Правило 1: знак на куспиде
        if cusp_sign in signs:
            ruled_houses.add(house_num)
            continue

        # Ретро-соуправление на куспиде
        if cusp_sign in SIGN_RULERS_RETRO:
            retro_ruler = SIGN_RULERS_RETRO[cusp_sign]
            if retro_ruler == planet_name and is_retrograde:
                ruled_houses.add(house_num)
                continue

        # Проходим по знакам внутри дома
        current_pos = cusp_start + deg_in_cusp_sign
        remaining = house_size - deg_in_cusp_sign

        while remaining > 0.1:
            current_pos = current_pos % 360
            sign_idx = int(current_pos / 30)
            sign = ZODIAC_SIGNS[sign_idx][0]

            deg_to_end = 30 - (current_pos % 30)
            deg_in_house = min(deg_to_end, remaining)

            is_included = deg_in_house >= 29.9
            is_over_50 = deg_in_house > (house_size / 2)
            is_over_13_5 = deg_in_house > 13.5

            if is_included or is_over_50 or is_over_13_5:
                if sign in signs:
                    ruled_houses.add(house_num)

                # Ретро-соуправление
                if sign in SIGN_RULERS_RETRO:
                    retro_ruler = SIGN_RULERS_RETRO[sign]
                    if retro_ruler == planet_name and is_retrograde:
                        ruled_houses.add(house_num)

            current_pos += deg_in_house
            remaining -= deg_in_house

    return sorted(ruled_houses)


def calculate_natal_with_formulas(
    birth_date: date,
    birth_time: str,
    birth_lat: float,
    birth_lon: float,
    timezone_hours: float = 3.0
) -> Dict:
    """
    Рассчитать натальную карту с формулами управления по Шестопалову.

    Returns:
        Словарь с данными планет и их управлениями
    """
    # Парсим время
    if hasattr(birth_time, 'hour'):
        hour, minute, second = birth_time.hour, birth_time.minute, getattr(birth_time, 'second', 0)
    else:
        parts = str(birth_time).split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0

    dt = datetime(birth_date.year, birth_date.month, birth_date.day, hour, minute, second)
    jd = datetime_to_julian(dt, timezone_hours)

    # Куспиды домов (Koch)
    cusps, ascmc = swe.houses(jd, birth_lat, birth_lon, b'K')
    cusps = list(cusps)

    # Позиции планет
    planets_data = {}
    retro_planets = set()

    for planet_id, (name, symbol) in PLANETS_ALL.items():
        try:
            result, _ = swe.calc_ut(jd, planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
            lon = result[0]
            speed = result[3]  # градусы/день

            sign_idx = int(lon / 30)
            is_retro = speed < 0

            if is_retro:
                retro_planets.add(name)

            planets_data[name] = {
                'longitude': lon,
                'sign': ZODIAC_SIGNS[sign_idx][0],
                'sign_symbol': ZODIAC_SIGNS[sign_idx][1],
                'degree': lon % 30,
                'house': get_planet_house(lon, cusps),
                'retro': is_retro,
                'symbol': symbol,
                'speed': speed,  # Скорость для определения Сх/Расх
            }
        except Exception as e:
            logger.warning(f"Ошибка расчёта {name}: {e}")

    # Рассчитываем управление домами для каждой планеты
    for name, data in planets_data.items():
        data['rules'] = get_planet_ruled_houses(
            name, cusps,
            is_retrograde=data['retro'],
            retro_planets=retro_planets
        )

    return {
        'planets': planets_data,
        'cusps': cusps,
        'asc': ascmc[0],
        'mc': ascmc[1],
        'retro_planets': retro_planets,
    }


# ============== АСПЕКТЫ И МАТРИЦА СВЯЗЕЙ ==============

# Аспекты с природой (базовые орбисы, переопределяются матрицей ниже)
ASPECTS_NATURE = {
    0: {'name': 'Соединение', 'symbol': '☌', 'orb': 8, 'nature': '±'},
    60: {'name': 'Секстиль', 'symbol': '⚹', 'orb': 6, 'nature': '+'},
    90: {'name': 'Квадратура', 'symbol': '□', 'orb': 8, 'nature': '-'},
    120: {'name': 'Тригон', 'symbol': '△', 'orb': 8, 'nature': '+'},
    180: {'name': 'Оппозиция', 'symbol': '☍', 'orb': 8, 'nature': '-'},
}

# ============== МАТРИЦА ОРБИСОВ ПО ШЕСТОПАЛОВУ ==============
# Орбисы зависят от пары планет (симметричная матрица)

# Порядок планет для индексации
ORB_PLANET_ORDER = [
    'Солнце', 'Луна', 'Меркурий', 'Венера', 'Марс',
    'Юпитер', 'Сатурн', 'Уран', 'Нептун', 'Плутон', 'Лилит'
]

# Матрица орбисов (симметричная)
# Строки/столбцы: Солнце, Луна, Меркурий, Венера, Марс, Юпитер, Сатурн, Уран, Нептун, Плутон, Лилит
ORB_MATRIX = [
    # Солн  Луна  Мерк  Вен   Марс  Юпит  Сат   Уран  Непт  Плут  Лилит
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Солнце
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Луна
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Меркурий
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Венера
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Марс
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Юпитер
    [9.0,  9.0,  9.0,  9.0,  9.0,  9.0,  9.0,  9.0,  9.0,  7.0,  5.0],  # Сатурн
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Уран
    [8.5,  8.5,  8.5,  8.5,  8.5,  8.5,  9.0,  8.5,  8.5,  6.5,  5.0],  # Нептун
    [6.5,  6.5,  6.5,  6.5,  6.5,  6.5,  7.0,  6.5,  6.5,  6.5,  5.0],  # Плутон
    [5.0,  5.0,  5.0,  5.0,  5.0,  5.0,  5.0,  5.0,  5.0,  5.0,  5.0],  # Лилит
]

# Злые планеты (1) vs Добрые (0) — влияет на интерпретацию
MALEFIC_PLANETS = {
    'Солнце': False, 'Луна': False, 'Меркурий': False, 'Венера': False,
    'Марс': True, 'Юпитер': False, 'Сатурн': True, 'Уран': True,
    'Нептун': True, 'Плутон': True, 'Лилит': True, 'Северный узел': False
}


def get_orb_for_planets(planet1: str, planet2: str) -> float:
    """
    Получить орбис для пары планет из матрицы Шестопалова.

    Args:
        planet1: Название первой планеты
        planet2: Название второй планеты

    Returns:
        Орбис в градусах
    """
    try:
        idx1 = ORB_PLANET_ORDER.index(planet1)
        idx2 = ORB_PLANET_ORDER.index(planet2)
        return ORB_MATRIX[idx1][idx2]
    except (ValueError, IndexError):
        # Для неизвестных планет (например, Северный узел) — стандартный орбис
        return 5.0

# Римские цифры для домов
ROMAN_NUMERALS = {
    1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI',
    7: 'VII', 8: 'VIII', 9: 'IX', 10: 'X', 11: 'XI', 12: 'XII'
}


def is_aspect_applying(
    lon1: float,
    lon2: float,
    speed1: float,
    speed2: float,
    aspect_angle: int
) -> bool:
    """
    Определить, является ли аспект сходящимся (applying).

    Сходящийся = планеты движутся к точному аспекту (орбис уменьшается).
    Расходящийся = планеты удаляются от точного аспекта (орбис увеличивается).

    Args:
        lon1: Долгота первой планеты
        lon2: Долгота второй планеты
        speed1: Скорость первой планеты (градусы/день)
        speed2: Скорость второй планеты (градусы/день)
        aspect_angle: Угол аспекта (0, 60, 90, 120, 180)

    Returns:
        True если сходящийся, False если расходящийся
    """
    # Текущее расстояние между планетами
    diff = lon1 - lon2
    if diff < -180:
        diff += 360
    elif diff > 180:
        diff -= 360

    # Относительная скорость (как быстро меняется расстояние)
    relative_speed = speed1 - speed2

    # Для каждого аспекта определяем, приближаемся или удаляемся
    # Аспект точен когда diff = ±aspect_angle

    if aspect_angle == 0:  # Соединение
        # Сходящийся если расстояние уменьшается
        if diff > 0:
            return relative_speed < 0
        else:
            return relative_speed > 0

    elif aspect_angle == 180:  # Оппозиция
        if diff > 0:
            # diff движется к 180
            return relative_speed > 0 if diff < 180 else relative_speed < 0
        else:
            # diff движется к -180
            return relative_speed < 0 if diff > -180 else relative_speed > 0

    else:  # Секстиль, Квадратура, Тригон
        # Проверяем ближайший точный аспект
        target_positive = aspect_angle
        target_negative = -aspect_angle

        dist_to_positive = abs(diff - target_positive)
        dist_to_negative = abs(diff - target_negative)

        if dist_to_positive < dist_to_negative:
            # Ближе к положительному углу
            return (diff < target_positive and relative_speed > 0) or \
                   (diff > target_positive and relative_speed < 0)
        else:
            # Ближе к отрицательному углу
            return (diff < target_negative and relative_speed > 0) or \
                   (diff > target_negative and relative_speed < 0)


def find_aspect(
    lon1: float,
    lon2: float,
    planet1_name: str = None,
    planet2_name: str = None,
    speed1: float = None,
    speed2: float = None
) -> Optional[Dict]:
    """
    Найти аспект между двумя долготами с учётом матрицы орбисов Шестопалова.

    Args:
        lon1: Долгота первой планеты
        lon2: Долгота второй планеты
        planet1_name: Имя первой планеты (для орбиса из матрицы)
        planet2_name: Имя второй планеты (для орбиса из матрицы)
        speed1: Скорость первой планеты (для Сх/Расх)
        speed2: Скорость второй планеты (для Сх/Расх)

    Returns:
        Словарь с данными аспекта или None
    """
    diff = abs(lon1 - lon2)
    if diff > 180:
        diff = 360 - diff

    # Получаем орбис из матрицы или используем стандартный
    if planet1_name and planet2_name:
        max_orb = get_orb_for_planets(planet1_name, planet2_name)
    else:
        max_orb = 8.5  # Стандартный орбис

    for angle, data in ASPECTS_NATURE.items():
        orb = abs(diff - angle)
        if orb <= max_orb:
            # Определяем сходящийся/расходящийся
            applying = None
            if speed1 is not None and speed2 is not None:
                applying = is_aspect_applying(lon1, lon2, speed1, speed2, angle)

            return {
                'angle': angle,
                'name': data['name'],
                'symbol': data['symbol'],
                'orb': orb,  # Точный орбис без округления
                'nature': data['nature'],
                'max_orb': max_orb,
                'applying': applying,  # True=Сх, False=Расх, None=неизвестно
            }
    return None


def calculate_natal_aspects(planets_data: Dict, cusps: List[float] = None) -> List[Dict]:
    """
    Рассчитать все аспекты между планетами в натальной карте.
    Использует матрицу орбисов Шестопалова.

    Args:
        planets_data: Словарь с данными планет
        cusps: Список куспидов домов (для аспектов планет к куспидам)

    Returns:
        Список аспектов
    """
    aspects = []
    planet_names = list(planets_data.keys())

    # Аспекты между планетами
    for i, p1_name in enumerate(planet_names):
        for p2_name in planet_names[i+1:]:
            p1 = planets_data[p1_name]
            p2 = planets_data[p2_name]

            # Передаём имена планет и скорости
            aspect = find_aspect(
                p1['longitude'],
                p2['longitude'],
                planet1_name=p1_name,
                planet2_name=p2_name,
                speed1=p1.get('speed', 0),
                speed2=p2.get('speed', 0)
            )
            if aspect:
                # Определяем злые/добрые планеты
                p1_malefic = MALEFIC_PLANETS.get(p1_name, False)
                p2_malefic = MALEFIC_PLANETS.get(p2_name, False)

                aspects.append({
                    'planet1': p1_name,
                    'planet2': p2_name,
                    'p1_symbol': p1.get('symbol', ''),
                    'p2_symbol': p2.get('symbol', ''),
                    'p1_house': p1['house'],
                    'p2_house': p2['house'],
                    'p1_rules': p1.get('rules', []),
                    'p2_rules': p2.get('rules', []),
                    'p1_retro': p1.get('retro', False),
                    'p2_retro': p2.get('retro', False),
                    'p1_malefic': p1_malefic,
                    'p2_malefic': p2_malefic,
                    'p1_speed': p1.get('speed', 0),
                    'p2_speed': p2.get('speed', 0),
                    'is_cusp_aspect': False,
                    **aspect
                })

    # Аспекты планет к куспидам домов (только соединения с орбисом до 1°)
    if cusps:
        CUSP_ORB = 1.0  # Орбис для аспектов к куспидам
        for p_name in planet_names:
            p = planets_data[p_name]
            p_lon = p['longitude']

            for house_num in range(1, 13):
                cusp_lon = cusps[house_num - 1]

                # Проверяем только соединение
                diff = abs(p_lon - cusp_lon)
                if diff > 180:
                    diff = 360 - diff

                if diff <= CUSP_ORB:
                    aspects.append({
                        'planet1': p_name,
                        'planet2': f'Куспид {ROMAN_NUMERALS[house_num]}',
                        'p1_symbol': p.get('symbol', ''),
                        'p2_symbol': '',
                        'p1_house': p['house'],
                        'p2_house': house_num,
                        'p1_rules': p.get('rules', []),
                        'p2_rules': [house_num],  # Куспид = дом
                        'p1_retro': p.get('retro', False),
                        'p2_retro': False,
                        'p1_malefic': MALEFIC_PLANETS.get(p_name, False),
                        'p2_malefic': False,
                        'p1_speed': p.get('speed', 0),
                        'p2_speed': 0,
                        'angle': 0,
                        'name': 'Соединение',
                        'symbol': '☌',
                        'orb': diff,
                        'nature': '±',
                        'max_orb': CUSP_ORB,
                        'applying': None,
                        'is_cusp_aspect': True,
                    })

    # Сортируем по орбису (точные аспекты первые)
    aspects.sort(key=lambda x: x['orb'])
    return aspects


def build_house_connections(aspects: List[Dict], planets_data: Dict) -> Dict:
    """
    Построить матрицу связей домов на основе аспектов.

    Формула связи: все дома планеты 1 (положение + управление)
                   связываются со всеми домами планеты 2

    Args:
        aspects: Список аспектов
        planets_data: Данные планет

    Returns:
        Словарь {(дом1, дом2): {'+': кол-во, '-': кол-во, '±': кол-во}}
    """
    connections = {}

    for asp in aspects:
        nature = asp['nature']

        # Все дома первой планеты (положение + управление)
        houses1 = [asp['p1_house']] + asp['p1_rules']
        houses1 = list(set(h for h in houses1 if h > 0))

        # Все дома второй планеты
        houses2 = [asp['p2_house']] + asp['p2_rules']
        houses2 = list(set(h for h in houses2 if h > 0))

        # Создаём связи между всеми парами домов
        for h1 in houses1:
            for h2 in houses2:
                if h1 == h2:
                    continue

                # Ключ — отсортированная пара
                key = tuple(sorted([h1, h2]))

                if key not in connections:
                    connections[key] = {'+': 0, '-': 0, '±': 0}

                connections[key][nature] += 1

    return connections


def format_house_matrix(connections: Dict) -> str:
    """
    Форматировать матрицу связей в читаемый вид.
    """
    lines = []
    lines.append("МАТРИЦА СВЯЗЕЙ ДОМОВ")
    lines.append("=" * 50)
    lines.append("")

    # Гармоничные связи
    lines.append("Гармоничные связи (+):")
    plus_conns = [(k, v['+']) for k, v in connections.items() if v['+'] > 0]
    plus_conns.sort(key=lambda x: -x[1])  # По убыванию
    for (h1, h2), count in plus_conns:
        lines.append(f"  {ROMAN_NUMERALS[h1]}-{ROMAN_NUMERALS[h2]}: {count}")

    lines.append("")

    # Напряжённые связи
    lines.append("Напряжённые связи (-):")
    minus_conns = [(k, v['-']) for k, v in connections.items() if v['-'] > 0]
    minus_conns.sort(key=lambda x: -x[1])
    for (h1, h2), count in minus_conns:
        lines.append(f"  {ROMAN_NUMERALS[h1]}-{ROMAN_NUMERALS[h2]}: {count}")

    return "\n".join(lines)


def calculate_full_natal_analysis(
    birth_date: date,
    birth_time: str,
    birth_lat: float,
    birth_lon: float,
    timezone_hours: float = 3.0
) -> Dict:
    """
    Полный анализ натальной карты по системе Шестопалова.

    Включает:
    - Позиции планет с домами и управлениями
    - Аспекты между планетами
    - Матрицу связей домов
    - Формулы событий

    Returns:
        Полные данные анализа
    """
    # 1. Базовый расчёт
    natal = calculate_natal_with_formulas(
        birth_date, birth_time, birth_lat, birth_lon, timezone_hours
    )

    # 2. Аспекты (включая аспекты к куспидам)
    aspects = calculate_natal_aspects(natal['planets'], cusps=natal['cusps'])

    # 3. Матрица связей
    connections = build_house_connections(aspects, natal['planets'])

    # 4. Форматируем данные для вывода
    result = {
        **natal,
        'aspects': aspects,
        'house_connections': connections,
        'matrix_text': format_house_matrix(connections),
    }

    # 5. Ищем сильные формулы (3+ указаний)
    strong_formulas = []
    for (h1, h2), counts in connections.items():
        total = counts['+'] + counts['-'] + counts['±']
        if total >= 3:
            strong_formulas.append({
                'houses': (h1, h2),
                'houses_roman': f"{ROMAN_NUMERALS[h1]}-{ROMAN_NUMERALS[h2]}",
                'positive': counts['+'],
                'negative': counts['-'],
                'neutral': counts['±'],
                'total': total,
            })

    strong_formulas.sort(key=lambda x: -x['total'])
    result['strong_formulas'] = strong_formulas

    return result


# ============== НАЗВАНИЯ ДОМОВ ==============

HOUSE_MEANINGS = {
    1: ("I дом", "Личность, внешность, начинания"),
    2: ("II дом", "Финансы, ценности, ресурсы"),
    3: ("III дом", "Коммуникации, поездки, обучение"),
    4: ("IV дом", "Дом, семья, корни"),
    5: ("V дом", "Творчество, дети, романтика"),
    6: ("VI дом", "Здоровье, работа, служение"),
    7: ("VII дом", "Партнёрство, брак, контракты"),
    8: ("VIII дом", "Трансформация, чужие деньги, секс"),
    9: ("IX дом", "Философия, путешествия, образование"),
    10: ("X дом", "Карьера, статус, репутация"),
    11: ("XI дом", "Друзья, цели, сообщества"),
    12: ("XII дом", "Подсознание, уединение, тайны"),
}


# ============== РАСШИРЕННАЯ ГЕНЕРАЦИЯ ДАННЫХ ==============

def generate_full_forecast_data(
    birth_date: date,
    birth_time: str,
    birth_lat: float,
    birth_lon: float,
    residence_lat: float = None,
    residence_lon: float = None,
    target_date: date = None,
    timezone_hours: float = 3.0
) -> Dict:
    """
    Сгенерировать полные данные для AI-прогноза с формулами Шестопалова

    Args:
        birth_date: Дата рождения
        birth_time: Время рождения
        birth_lat: Широта рождения
        birth_lon: Долгота рождения
        residence_lat: Широта проживания (для текущих домов)
        residence_lon: Долгота проживания
        target_date: Дата прогноза
        timezone_hours: Часовой пояс

    Returns:
        Полные данные для Groq
    """
    from data.shestopalov import (
        get_transit_interpretation,
        get_transit_priority,
        PLANET_MEANINGS,
        check_active_formulas,
        format_formula_for_ai,
        calculate_transit_formula
    )

    if target_date is None:
        target_date = date.today()

    if residence_lat is None:
        residence_lat = birth_lat
    if residence_lon is None:
        residence_lon = birth_lon

    # Парсим время (может быть строка или datetime.time)
    if hasattr(birth_time, 'hour'):
        # datetime.time объект
        hour = birth_time.hour
        minute = birth_time.minute
    else:
        # Строка "HH:MM" или "HH:MM:SS"
        time_parts = str(birth_time).split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0

    birth_dt = datetime(birth_date.year, birth_date.month, birth_date.day, hour, minute)
    target_dt = datetime.combine(target_date, datetime.now().time())

    birth_jd = datetime_to_julian(birth_dt, timezone_hours)
    target_jd = datetime_to_julian(target_dt, timezone_hours)

    # Натальные данные (позиции планет по месту рождения)
    natal = get_natal_chart(birth_date, birth_time, birth_lat, birth_lon, timezone_hours)

    # ЛОКАЛЬНАЯ КАРТА (релокация): дома строятся по месту проживания!
    # Это стандарт в системе Шестопалова
    natal_houses = calculate_houses(birth_jd, residence_lat, residence_lon)

    # Сохраняем куспиды для расчёта формул (долготы, не знаки!)
    natal_cusps = natal_houses.cusps

    # Транзитные данные
    transits = get_transits(target_dt, timezone_hours)
    transit_houses = calculate_houses(target_jd, residence_lat, residence_lon)

    # Аспекты
    aspects = get_transit_aspects(natal, transits)

    # Фаза Луны
    moon_phase = get_moon_phase(target_jd)

    # Формируем данные
    data = {
        "date": target_date.isoformat(),
        "moon_phase": moon_phase,
        "natal": {
            "positions": {},
            "houses": {
                "asc": round(natal_houses.asc, 1),
                "mc": round(natal_houses.mc, 1)
            }
        },
        "transits": {
            "positions": {}
        },
        "aspects_detailed": [],
        "key_themes": [],
        "recommendations": []
    }

    # Натальные позиции с домами
    for planet_id, pos in natal.items():
        house = get_planet_house(pos.longitude, natal_houses.cusps)
        data["natal"]["positions"][pos.name] = {
            "sign": pos.sign,
            "degree": round(pos.degree_in_sign, 1),
            "house": house,
            "retrograde": pos.is_retrograde
        }

    # Транзитные позиции с домами
    for planet_id, pos in transits.items():
        house = get_planet_house(pos.longitude, transit_houses.cusps)
        data["transits"]["positions"][pos.name] = {
            "sign": pos.sign,
            "degree": round(pos.degree_in_sign, 1),
            "house": house,
            "retrograde": pos.is_retrograde
        }

    # Детальные аспекты с интерпретациями
    for aspect in aspects[:10]:
        # Извлекаем имена планет
        t_name = aspect.planet1.split()[-1]  # "☉ тр. Солнце" -> "Солнце"
        n_name = aspect.planet2.split()[-1]

        interpretation = get_transit_interpretation(t_name, n_name, aspect.aspect_name)
        priority = get_transit_priority(t_name, aspect.orb)

        # Получаем данные о позиции и ретроградности
        transit_data = data["transits"]["positions"].get(t_name, {})
        natal_data = data["natal"]["positions"].get(n_name, {})

        transit_house = transit_data.get("house", 0)
        natal_house = natal_data.get("house", 0)
        transit_is_retrograde = transit_data.get("retrograde", False)
        natal_is_retrograde = natal_data.get("retrograde", False)

        # Вычисляем формулу по управлению планет (с учётом ретроградности)
        formula = calculate_transit_formula(
            transit_planet=t_name,
            natal_planet=n_name,
            cusps=natal_cusps,  # Передаём долготы куспидов
            transit_house=transit_house,
            natal_house=natal_house,
            aspect_nature=interpretation.get("nature", "neutral"),
            natal_is_retrograde=natal_is_retrograde,
            transit_is_retrograde=transit_is_retrograde
        )

        data["aspects_detailed"].append({
            "transit": aspect.planet1,
            "natal": aspect.planet2,
            "aspect": aspect.aspect_name,
            "symbol": aspect.aspect_symbol,
            "orb": aspect.orb,
            "transit_house": transit_house,
            "natal_house": natal_house,
            "formula": formula,  # Формула по управлению (например "1,8 → 2,7")
            "nature": interpretation.get("nature", "нейтральный"),
            "effects": interpretation.get("possible_effects", []),
            "advice": interpretation.get("advice", ""),
            "priority": round(priority, 1)
        })

        # Добавляем ключевые темы
        if priority > 5:
            sphere = interpretation.get("transit_sphere", "")
            if sphere and sphere not in data["key_themes"]:
                data["key_themes"].append(sphere)

    # Сортируем по приоритету
    data["aspects_detailed"].sort(key=lambda x: x["priority"], reverse=True)

    # Генерируем рекомендации на основе топ-аспектов
    for asp in data["aspects_detailed"][:3]:
        if asp.get("advice"):
            data["recommendations"].append(asp["advice"])

    # Подготавливаем данные для анализа формул Шестопалова
    transits_for_formulas = []
    for asp in data["aspects_detailed"]:
        # Извлекаем имена планет без префиксов
        t_parts = asp["transit"].split()
        n_parts = asp["natal"].split()
        t_name = t_parts[-1] if t_parts else ""
        n_name = n_parts[-1] if n_parts else ""

        transits_for_formulas.append({
            "transit_planet": t_name,
            "natal_planet": n_name,
            "aspect": asp["aspect"],
            "natal_house": asp["natal_house"],
            "transit_house": asp["transit_house"]
        })

    # Создаём словарь домов натальных планет
    natal_houses_dict = {}
    for planet_name, pos_data in data["natal"]["positions"].items():
        natal_houses_dict[planet_name] = pos_data.get("house", 0)

    # Проверяем активные формулы событий
    active_formulas = check_active_formulas(transits_for_formulas, natal_houses_dict)
    data["active_formulas"] = active_formulas
    data["formulas_text"] = format_formula_for_ai(active_formulas)

    # Добавляем описания домов
    data["house_meanings"] = HOUSE_MEANINGS

    return data


# ============== ФОРМАТИРОВАНИЕ АСПЕКТОВ С ФОРМУЛАМИ ==============

def format_aspect_formula(house: int, rules: List[int]) -> str:
    """
    Форматирование формулы: позиция (управление)

    По Шестопалову:
    - Перед скобками: дом положения
    - В скобках: дома управления (могут включать дом положения, если планета им управляет)
    - Если планета не управляет домами (например, Северный узел) — только номер дома без скобок

    Примеры:
    - Солнце H4 упр(3,4) → "4 (3 4)" — управляет 4 домом
    - Марс H3 упр(6) → "3 (6)" — не управляет 3 домом
    - Юпитер H9 упр(7,10,11) → "9 (7 10 11)"
    - Сев.узел H12 упр() → "12" — без скобок

    Args:
        house: Дом положения планеты
        rules: Список домов управления

    Returns:
        Строка вида "4 (3 4)" или "3 (6)" или "12"
    """
    if not rules:
        return str(house)
    return f"{house} ({' '.join(map(str, sorted(rules)))})"


def format_orb_dms(degrees: float) -> str:
    """Форматирование орбиса в градусы°минуты'секунды\""""
    d = int(degrees)
    m = int((degrees - d) * 60)
    s = int(((degrees - d) * 60 - m) * 60)
    return f"{d:02d}°{m:02d}'{s:02d}\""


def format_natal_aspects_text(
    aspects: List[Dict],
    planet_order: List[str] = None
) -> str:
    """
    Форматирование списка натальных аспектов с формулами событий.
    Формат эталона Шестопалова:
    ☉H ☌ ☿HR 07°02'09" Сх  1 (2) ± 1 (2 3 11)

    Args:
        aspects: Список аспектов из calculate_natal_aspects()
        planet_order: Порядок планет для сортировки

    Returns:
        Текстовое представление аспектов
    """
    if planet_order is None:
        planet_order = [
            'Солнце', 'Луна', 'Меркурий', 'Венера', 'Марс',
            'Юпитер', 'Сатурн', 'Уран', 'Нептун', 'Плутон',
            'Лилит', 'Северный узел'
        ]

    def get_sort_key(asp):
        p1, p2 = asp['planet1'], asp['planet2']
        if 'Куспид' in p1:
            return (100, 0)
        if 'Куспид' in p2:
            idx1 = planet_order.index(p1) if p1 in planet_order else 99
            return (50 + idx1, 0)
        idx1 = planet_order.index(p1) if p1 in planet_order else 99
        idx2 = planet_order.index(p2) if p2 in planet_order else 99
        return (idx1, idx2)

    sorted_aspects = sorted(aspects, key=get_sort_key)
    lines = []

    for asp in sorted_aspects:
        p1, p2 = asp['planet1'], asp['planet2']
        sym1, sym2 = asp['p1_symbol'], asp.get('p2_symbol', '')
        h1, h2 = asp['p1_house'], asp['p2_house']
        r1, r2 = asp.get('p1_retro', False), asp.get('p2_retro', False)
        rules1 = asp.get('p1_rules', [])
        rules2 = asp.get('p2_rules', [])

        # Суффикс H/HR
        s1 = 'HR' if r1 else 'H'
        s2 = 'HR' if r2 else 'H'

        # Сх/Расх
        applying = asp.get('applying')
        if asp.get('is_cusp_aspect'):
            appl_str = '    '
        elif applying is True:
            appl_str = 'Сх  '
        elif applying is False:
            appl_str = 'Расх'
        else:
            appl_str = '    '

        # Формулы
        f1 = format_aspect_formula(h1, rules1)

        # Для куспидов
        if 'Куспид' in p2:
            cusp_sym = ROMAN_NUMERALS.get(h2, str(h2))
            f2 = str(h2)
            line = f"{sym1}{s1:2} {asp['symbol']} {cusp_sym:>4} {format_orb_dms(asp['orb']):>11} {appl_str}  {f1} {asp['nature']} {f2}"
        else:
            f2 = format_aspect_formula(h2, rules2)
            line = f"{sym1}{s1:2} {asp['symbol']} {sym2}{s2:2} {format_orb_dms(asp['orb']):>10} {appl_str}  {f1} {asp['nature']} {f2}"

        lines.append(line)

    return '\n'.join(lines)


def calculate_local_natal(
    birth_date: date,
    birth_time: str,
    birth_lat: float,
    birth_lon: float,
    residence_lat: float,
    residence_lon: float,
    timezone_hours: float = 3.0
) -> Dict:
    """
    Рассчитать локальную натальную карту (релокация).

    Планеты = по месту рождения (натальные позиции не меняются)
    Дома = по месту проживания (релоцированные)

    Args:
        birth_date: Дата рождения
        birth_time: Время рождения
        birth_lat: Широта места рождения
        birth_lon: Долгота места рождения
        residence_lat: Широта места проживания
        residence_lon: Долгота места проживания
        timezone_hours: Часовой пояс рождения

    Returns:
        Словарь с данными локальной карты
    """
    # Парсим время
    if hasattr(birth_time, 'hour'):
        hour, minute = birth_time.hour, birth_time.minute
        second = getattr(birth_time, 'second', 0)
    else:
        parts = str(birth_time).split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0

    dt = datetime(birth_date.year, birth_date.month, birth_date.day, hour, minute, second)
    jd = datetime_to_julian(dt, timezone_hours)

    # ПЛАНЕТЫ по месту рождения (не меняются)
    planets_data = {}
    retro_planets = set()

    for planet_id, (name, symbol) in PLANETS_ALL.items():
        try:
            result, _ = swe.calc_ut(jd, planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
            lon = result[0]
            speed = result[3]

            sign_idx = int(lon / 30)
            is_retro = speed < 0

            if is_retro:
                retro_planets.add(name)

            planets_data[name] = {
                'longitude': lon,
                'sign': ZODIAC_SIGNS[sign_idx][0],
                'sign_symbol': ZODIAC_SIGNS[sign_idx][1],
                'degree': lon % 30,
                'retro': is_retro,
                'symbol': symbol,
                'speed': speed,
            }
        except Exception as e:
            logger.warning(f"Ошибка расчёта {name}: {e}")

    # ДОМА по месту проживания (релокация!)
    local_cusps, local_ascmc = swe.houses(jd, residence_lat, residence_lon, b'K')
    local_cusps = list(local_cusps)

    # Определяем дом каждой планеты по локальным куспидам
    for name, data in planets_data.items():
        data['house'] = get_planet_house(data['longitude'], local_cusps)

    # Рассчитываем управление домами
    for name, data in planets_data.items():
        data['rules'] = get_planet_ruled_houses(
            name, local_cusps,
            is_retrograde=data['retro'],
            retro_planets=retro_planets
        )

    # Аспекты (включая аспекты к куспидам)
    aspects = calculate_natal_aspects(planets_data, cusps=local_cusps)

    # Матрица связей домов
    connections = build_house_connections(aspects, planets_data)

    return {
        'planets': planets_data,
        'cusps': local_cusps,
        'asc': local_ascmc[0],
        'mc': local_ascmc[1],
        'retro_planets': retro_planets,
        'aspects': aspects,
        'house_connections': connections,
        'birth_coords': (birth_lat, birth_lon),
        'residence_coords': (residence_lat, residence_lon),
        'is_relocated': (birth_lat != residence_lat or birth_lon != residence_lon),
    }


# ============== ТРАНЗИТЫ ==============

# Орбисы для транзитов (меньше чем для натальных аспектов)
TRANSIT_ORBS = {
    0: 1.0,     # Соединение
    60: 1.0,    # Секстиль
    90: 1.0,    # Квадрат
    120: 1.0,   # Трин
    180: 1.0,   # Оппозиция
}


def find_exact_aspect_time(
    natal_lon: float,
    transit_planet_id: int,
    aspect_angle: float,
    jd_start: float,
    jd_end: float,
    precision_minutes: float = 1.0
) -> Optional[Tuple[float, float, bool]]:
    """
    Найти точное время аспекта методом бинарного поиска.

    Args:
        natal_lon: Долгота натальной планеты
        transit_planet_id: ID транзитной планеты
        aspect_angle: Угол аспекта (0, 60, 90, 120, 180)
        jd_start: Начало интервала (Julian Day)
        jd_end: Конец интервала (Julian Day)
        precision_minutes: Точность в минутах

    Returns:
        (julian_day, orb, is_applying) или None
    """
    precision_jd = precision_minutes / 1440.0  # минуты → дни

    # Целевая долгота для точного аспекта
    target_lons = [
        (natal_lon + aspect_angle) % 360,
        (natal_lon - aspect_angle) % 360
    ]

    for target_lon in target_lons:
        jd = jd_start
        prev_diff = None

        while jd < jd_end:
            result, _ = swe.calc_ut(jd, transit_planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
            transit_lon = result[0]
            speed = result[3]

            # Разница до целевой долготы
            diff = transit_lon - target_lon
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360

            # Проверяем пересечение нуля
            if prev_diff is not None:
                if (prev_diff < 0 and diff >= 0) or (prev_diff > 0 and diff <= 0):
                    # Нашли пересечение, уточняем бинарным поиском
                    jd_left, jd_right = jd - precision_jd * 60, jd

                    for _ in range(20):  # 20 итераций достаточно для точности до секунды
                        jd_mid = (jd_left + jd_right) / 2
                        result_mid, _ = swe.calc_ut(jd_mid, transit_planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
                        mid_lon = result_mid[0]
                        mid_speed = result_mid[3]

                        mid_diff = mid_lon - target_lon
                        if mid_diff > 180:
                            mid_diff -= 360
                        elif mid_diff < -180:
                            mid_diff += 360

                        if abs(mid_diff) < 0.00001:  # Достаточная точность
                            break

                        if (mid_diff < 0) == (prev_diff < 0):
                            jd_left = jd_mid
                        else:
                            jd_right = jd_mid

                    # Определяем сходящийся/расходящийся
                    # Сходящийся = движется к точному аспекту
                    is_applying = (mid_diff < 0 and mid_speed > 0) or (mid_diff > 0 and mid_speed < 0)

                    return (jd_mid, abs(mid_diff), is_applying)

            prev_diff = diff
            jd += precision_jd * 60  # Шаг 1 час

    return None


def calculate_transits(
    natal_data: Dict,
    start_date: date,
    days: int = 7,
    residence_lat: float = None,
    residence_lon: float = None,
    timezone_hours: float = 3.0,
    transit_cusps_tz: float = 7.0
) -> List[Dict]:
    """
    Рассчитать транзиты (транзитные планеты к натальным) на период.

    По Шестопалову:
    - Дом транзитной планеты = по НАТАЛЬНЫМ куспидам (через какой натальный дом проходит)
    - Управление транзитной планеты = ОБЪЕДИНЕНИЕ натальных и транзитных куспидов

    Args:
        natal_data: Данные натальной карты (из calculate_local_natal или calculate_natal_chart)
        start_date: Начальная дата периода
        days: Количество дней
        residence_lat: Широта места (для расчёта куспидов момента транзита)
        residence_lon: Долгота места
        timezone_hours: Часовой пояс для отображения времени
        transit_cusps_tz: Часовой пояс для расчёта транзитных куспидов (TZ+7 для Белово)

    Returns:
        Список транзитных аспектов с временем точного аспекта
    """
    transits = []

    # Начало и конец периода
    dt_start = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
    jd_start = datetime_to_julian(dt_start, timezone_hours)
    jd_end = jd_start + days

    # НАТАЛЬНЫЕ куспиды — для определения дома транзитной планеты
    natal_cusps = natal_data.get('cusps', [0] * 12)

    # Координаты для расчёта куспидов момента транзита
    if residence_lat is None:
        residence_lat = natal_data.get('birth_coords', (0, 0))[0]
    if residence_lon is None:
        residence_lon = natal_data.get('birth_coords', (0, 0))[1]

    # Натальные позиции планет
    natal_planets = natal_data['planets']

    # Итерация по всем транзитным планетам
    for transit_id, (transit_name, transit_symbol) in PLANETS_ALL.items():
        # Шаг поиска зависит от скорости планеты
        # Луна: каждые 6 минут, быстрые: каждые 15 минут, медленные: каждый час
        if transit_id == swe.MOON:
            step_hours = 0.1  # 6 минут
        elif transit_id in [swe.SUN, swe.MERCURY, swe.VENUS, swe.MARS]:
            step_hours = 0.25  # 15 минут
        else:
            step_hours = 1  # 1 час

        step_jd = step_hours / 24.0

        # Для каждой натальной планеты
        for natal_name, natal_data_item in natal_planets.items():
            natal_lon = natal_data_item['longitude']
            natal_house = natal_data_item['house']
            natal_rules = natal_data_item.get('rules', [])
            natal_symbol = natal_data_item['symbol']
            natal_retro = natal_data_item.get('retro', False)

            # Для каждого аспекта
            for aspect_angle, (aspect_name, aspect_symbol, base_orb) in ASPECTS.items():
                # Орбис для транзитов
                max_orb = TRANSIT_ORBS.get(aspect_angle, 1.0)

                # Ищем точные аспекты
                jd = jd_start
                prev_orb = None
                prev_direction = None  # True = приближается, False = отдаляется

                while jd < jd_end:
                    try:
                        result, _ = swe.calc_ut(jd, transit_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
                        transit_lon = result[0]
                        transit_speed = result[3]
                    except:
                        jd += step_jd
                        continue

                    # Вычисляем орб аспекта
                    diff = abs(transit_lon - natal_lon)
                    if diff > 180:
                        diff = 360 - diff

                    # Отклонение от точного аспекта
                    orb = min(abs(diff - aspect_angle), abs(360 - diff - aspect_angle))

                    # Определяем направление
                    if prev_orb is not None:
                        current_direction = orb < prev_orb  # True = приближается

                        # Переход через точный аспект (направление изменилось с приближения на отдаление)
                        if prev_direction is True and current_direction is False and orb < max_orb:
                            # Уточняем время точного аспекта
                            jd_exact = jd - step_jd / 2

                            # Бинарный поиск для точного времени
                            jd_left, jd_right = jd - step_jd, jd
                            for _ in range(20):
                                jd_mid = (jd_left + jd_right) / 2
                                result_mid, _ = swe.calc_ut(jd_mid, transit_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
                                mid_lon = result_mid[0]
                                mid_speed = result_mid[3]

                                mid_diff = abs(mid_lon - natal_lon)
                                if mid_diff > 180:
                                    mid_diff = 360 - mid_diff
                                mid_orb = min(abs(mid_diff - aspect_angle), abs(360 - mid_diff - aspect_angle))

                                # Сравниваем с серединой
                                result_left, _ = swe.calc_ut(jd_left, transit_id, swe.FLG_SWIEPH)
                                left_lon = result_left[0]
                                left_diff = abs(left_lon - natal_lon)
                                if left_diff > 180:
                                    left_diff = 360 - left_diff
                                left_orb = min(abs(left_diff - aspect_angle), abs(360 - left_diff - aspect_angle))

                                if left_orb < mid_orb:
                                    jd_right = jd_mid
                                else:
                                    jd_left = jd_mid

                                if abs(jd_right - jd_left) < 1/86400:  # Точность до секунды
                                    break

                            jd_exact = (jd_left + jd_right) / 2

                            # Получаем данные в момент точного аспекта
                            result_exact, _ = swe.calc_ut(jd_exact, transit_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
                            exact_lon = result_exact[0]
                            exact_speed = result_exact[3]
                            is_retro = exact_speed < 0

                            # Дом транзитной планеты — по НАТАЛЬНЫМ куспидам
                            transit_house = get_planet_house(exact_lon, natal_cusps)

                            # ФОРМУЛА ТРАНЗИТНОЙ ПЛАНЕТЫ ПО ШЕСТОПАЛОВУ:
                            # Управление = дом НАТАЛЬНОЙ планеты + управление НАТАЛЬНОЙ планеты
                            # (транзитная планета "несёт" формулу своей натальной версии)
                            natal_planet_data = natal_planets.get(transit_name)
                            if natal_planet_data:
                                natal_planet_house = natal_planet_data['house']
                                natal_planet_rules = natal_planet_data.get('rules', [])
                                # Объединяем: дом натальной + её управление
                                transit_rules = sorted(set([natal_planet_house] + natal_planet_rules))
                            else:
                                # Если планеты нет в натале, используем только управление по куспидам
                                transit_rules = get_planet_ruled_houses(
                                    transit_name, natal_cusps,
                                    is_retrograde=is_retro,
                                    retro_planets=set()
                                )

                            # Сходящийся/расходящийся (в момент точного аспекта всегда расходящийся)
                            # Но мы показываем направление до аспекта
                            is_applying = False  # После точного = расходящийся

                            # Конвертируем JD в datetime
                            exact_dt = julian_to_datetime(jd_exact, timezone_hours)

                            transits.append({
                                'transit_planet': transit_name,
                                'transit_symbol': transit_symbol,
                                'transit_house': transit_house,
                                'transit_rules': transit_rules,
                                'transit_retro': is_retro,
                                'natal_planet': natal_name,
                                'natal_symbol': natal_symbol,
                                'natal_house': natal_house,
                                'natal_rules': natal_rules,
                                'natal_retro': natal_retro,
                                'aspect_name': aspect_name,
                                'aspect_symbol': aspect_symbol,
                                'aspect_angle': aspect_angle,
                                'exact_datetime': exact_dt,
                                'exact_jd': jd_exact,
                                'is_applying': is_applying,
                            })

                        prev_direction = current_direction
                    else:
                        # Первая итерация - определяем начальное направление
                        prev_direction = None

                    prev_orb = orb
                    jd += step_jd

    # Сортируем по времени
    transits.sort(key=lambda x: x['exact_jd'])

    return transits


def julian_to_datetime(jd: float, timezone_hours: float = 0) -> datetime:
    """Конвертация Julian Day в datetime"""
    # Получаем UTC
    year, month, day, hour_float = swe.revjul(jd)
    hour = int(hour_float)
    minute_float = (hour_float - hour) * 60
    minute = int(minute_float)
    second = int((minute_float - minute) * 60)

    dt_utc = datetime(year, month, day, hour, minute, second)

    # Добавляем смещение часового пояса
    dt_local = dt_utc + timedelta(hours=timezone_hours)

    return dt_local


def format_transits_text(transits: List[Dict]) -> str:
    """
    Форматирование списка транзитов в текст.

    Формат эталона (Altair):
    ☽т ♂ ☽н 11.01.2026 01:49:58 4 (10 12) - 10 (12)

    Символы аспектов Altair:
    - * = секстиль (60°)
    - □ = квадратура (90°)
    - △ = тригон (120°)
    - ♂ = оппозиция (180°)  НЕ Марс!
    - ☌ = соединение (0°)

    Args:
        transits: Список транзитов из calculate_transits()

    Returns:
        Текстовое представление
    """
    # Символы аспектов в формате Altair
    ALTAIR_SYMBOLS = {
        0: '☌',     # Соединение
        60: '*',    # Секстиль (звёздочка)
        90: '□',    # Квадратура
        120: '△',   # Тригон
        180: '♂',   # Оппозиция (НЕ Марс!)
    }

    # Природа аспектов
    ASPECT_NATURE = {
        0: '±',     # Соединение — зависит от планет
        60: '+',    # Секстиль — гармоничный
        90: '-',    # Квадратура — напряжённый
        120: '+',   # Тригон — гармоничный
        180: '-',   # Оппозиция — напряжённый
    }

    lines = []

    for tr in transits:
        # Транзитная планета с индексом "т"
        t_sym = tr['transit_symbol']
        t_suffix = 'R' if tr['transit_retro'] else ''
        transit_str = f"{t_sym}т{t_suffix}"

        # Аспект в формате Altair
        aspect_angle = tr['aspect_angle']
        aspect_str = ALTAIR_SYMBOLS.get(aspect_angle, tr['aspect_symbol'])

        # Натальная планета с индексом "н"
        n_sym = tr['natal_symbol']
        n_suffix = 'R' if tr['natal_retro'] else ''
        natal_str = f"{n_sym}н{n_suffix}"

        # Дата/время
        dt = tr['exact_datetime']
        datetime_str = dt.strftime('%d.%m.%Y %H:%M:%S')

        # Формулы
        t_formula = format_aspect_formula(tr['transit_house'], tr['transit_rules'])

        # Для натальной планеты: исключаем дом положения из управления
        # (он уже указан перед скобками)
        natal_rules_filtered = [r for r in tr['natal_rules'] if r != tr['natal_house']]
        n_formula = format_aspect_formula(tr['natal_house'], natal_rules_filtered)

        # Природа аспекта (+ / - / ±)
        nature = ASPECT_NATURE.get(aspect_angle, '±')

        # Собираем строку
        line = f"{transit_str:4} {aspect_str} {natal_str:4}   {datetime_str}   {t_formula} {nature} {n_formula}"
        lines.append(line)

    return '\n'.join(lines)


# ==============================================================================
# ФАЗЫ ЛУНЫ
# ==============================================================================

# Названия фаз Луны
MOON_PHASES = [
    ("Новолуние", "🌑"),
    ("Молодая Луна", "🌒"),
    ("Первая четверть", "🌓"),
    ("Прибывающая Луна", "🌔"),
    ("Полнолуние", "🌕"),
    ("Убывающая Луна", "🌖"),
    ("Последняя четверть", "🌗"),
    ("Старая Луна", "🌘"),
]


def get_moon_phase_info(dt: datetime = None) -> Dict:
    """
    Получить информацию о текущей фазе Луны.

    Args:
        dt: Дата и время (по умолчанию — сейчас)

    Returns:
        Словарь с информацией о Луне
    """
    if dt is None:
        dt = datetime.now()

    jd = datetime_to_julian(dt)

    # Позиции Солнца и Луны
    sun_pos = swe.calc_ut(jd, swe.SUN)[0]
    moon_pos = swe.calc_ut(jd, swe.MOON)[0]

    sun_lon = sun_pos[0]
    moon_lon = moon_pos[0]

    # Элонгация (угол между Луной и Солнцем)
    elongation = (moon_lon - sun_lon) % 360

    # Процент освещённости (приблизительно)
    illumination = (1 - abs(180 - elongation) / 180) * 100
    # Более точный расчёт через косинус
    illumination = (1 - abs(elongation - 180) / 180) * 100
    if elongation > 180:
        illumination = (1 - (360 - elongation) / 180) * 100

    # Фаза (0-7)
    phase_index = int(elongation / 45) % 8
    phase_name, phase_emoji = MOON_PHASES[phase_index]

    # Лунный день (1-30)
    lunar_day = int(elongation / 12.2) + 1
    if lunar_day > 30:
        lunar_day = 30

    # Знак зодиака Луны
    moon_sign_index = int(moon_lon / 30)
    moon_sign, moon_sign_symbol = ZODIAC_SIGNS[moon_sign_index]
    moon_degree = moon_lon % 30

    # Растущая или убывающая
    is_waxing = elongation < 180

    return {
        "date": dt.strftime("%d.%m.%Y"),
        "time": dt.strftime("%H:%M"),
        "phase_name": phase_name,
        "phase_emoji": phase_emoji,
        "phase_index": phase_index,  # 0-7
        "lunar_day": lunar_day,
        "illumination": round(illumination, 1),
        "elongation": round(elongation, 2),
        "is_waxing": is_waxing,
        "moon_sign": moon_sign,
        "moon_sign_symbol": moon_sign_symbol,
        "moon_degree": round(moon_degree, 1),
    }


def find_next_new_moon(from_date: datetime = None) -> datetime:
    """Найти дату следующего новолуния."""
    if from_date is None:
        from_date = datetime.now()

    jd = datetime_to_julian(from_date)

    # Ищем момент когда Луна-Солнце = 0°
    for day_offset in range(30):
        check_jd = jd + day_offset
        sun_lon = swe.calc_ut(check_jd, swe.SUN)[0][0]
        moon_lon = swe.calc_ut(check_jd, swe.MOON)[0][0]
        elongation = (moon_lon - sun_lon) % 360

        if elongation < 12 or elongation > 348:
            # Уточняем время
            for hour in range(24):
                check_jd_h = check_jd + hour / 24
                sun_lon = swe.calc_ut(check_jd_h, swe.SUN)[0][0]
                moon_lon = swe.calc_ut(check_jd_h, swe.MOON)[0][0]
                elongation = (moon_lon - sun_lon) % 360
                if elongation < 6 or elongation > 354:
                    return julian_to_datetime(check_jd_h)

    return from_date + timedelta(days=29)


def find_next_full_moon(from_date: datetime = None) -> datetime:
    """Найти дату следующего полнолуния."""
    if from_date is None:
        from_date = datetime.now()

    jd = datetime_to_julian(from_date)

    # Ищем момент когда Луна-Солнце = 180°
    for day_offset in range(30):
        check_jd = jd + day_offset
        sun_lon = swe.calc_ut(check_jd, swe.SUN)[0][0]
        moon_lon = swe.calc_ut(check_jd, swe.MOON)[0][0]
        elongation = (moon_lon - sun_lon) % 360

        if 168 < elongation < 192:
            # Уточняем время
            for hour in range(24):
                check_jd_h = check_jd + hour / 24
                sun_lon = swe.calc_ut(check_jd_h, swe.SUN)[0][0]
                moon_lon = swe.calc_ut(check_jd_h, swe.MOON)[0][0]
                elongation = (moon_lon - sun_lon) % 360
                if 174 < elongation < 186:
                    return julian_to_datetime(check_jd_h)

    return from_date + timedelta(days=15)


def find_next_eclipses(from_date: datetime = None, count: int = 2) -> List[Dict]:
    """
    Найти ближайшие лунные затмения.

    Args:
        from_date: Начальная дата поиска
        count: Количество затмений для поиска

    Returns:
        Список лунных затмений с датами и типами
    """
    if from_date is None:
        from_date = datetime.now()

    jd = datetime_to_julian(from_date)
    eclipses = []

    try:
        # Поиск лунных затмений
        current_jd = jd
        for i in range(count):
            result = swe.lun_eclipse_when(current_jd, swe.FLG_SWIEPH)
            if result[0]:
                eclipse_jd = result[1][0]
                eclipse_dt = julian_to_datetime(eclipse_jd)

                eclipse_type = "Лунное затмение"
                if result[0] & swe.ECL_TOTAL:
                    eclipse_type = "Полное лунное затмение"
                elif result[0] & swe.ECL_PENUMBRAL:
                    eclipse_type = "Полутеневое лунное затмение"
                elif result[0] & swe.ECL_PARTIAL:
                    eclipse_type = "Частное лунное затмение"

                eclipses.append({
                    "date": eclipse_dt.strftime("%d.%m.%Y"),
                    "time": eclipse_dt.strftime("%H:%M"),
                    "type": eclipse_type,
                    "emoji": "🌕",
                    "is_solar": False,
                })
                # Сдвигаем дату для поиска следующего затмения
                current_jd = eclipse_jd + 30  # +30 дней после найденного
    except Exception as e:
        logger.warning(f"Ошибка поиска затмений: {e}")

    return eclipses[:count]


def get_full_moon_info(dt: datetime = None) -> Dict:
    """
    Получить полную информацию о Луне для виджета.

    Returns:
        Словарь со всей информацией о Луне
    """
    if dt is None:
        dt = datetime.now()

    # Текущая фаза
    phase_info = get_moon_phase_info(dt)

    # Ближайшие новолуние и полнолуние
    next_new = find_next_new_moon(dt)
    next_full = find_next_full_moon(dt)

    # Ближайшие затмения
    eclipses = find_next_eclipses(dt, 2)

    return {
        **phase_info,
        "next_new_moon": next_new.strftime("%d.%m.%Y"),
        "next_full_moon": next_full.strftime("%d.%m.%Y"),
        "eclipses": eclipses,
    }


def julian_to_datetime(jd: float) -> datetime:
    """Конвертация Julian Day в datetime."""
    result = swe.revjul(jd)
    year, month, day, hour_float = result
    hours = int(hour_float)
    minutes = int((hour_float - hours) * 60)
    return datetime(year, month, day, hours, minutes)


# ==============================================================================
# РЕТРОГРАДНЫЕ ПЕРИОДЫ
# ==============================================================================

# Планеты которые могут быть ретроградными (без Солнца и Луны)
RETROGRADE_PLANETS = {
    swe.MERCURY: ("Меркурий", "☿", "#8B5CF6"),
    swe.VENUS: ("Венера", "♀", "#EC4899"),
    swe.MARS: ("Марс", "♂", "#EF4444"),
    swe.JUPITER: ("Юпитер", "♃", "#F59E0B"),
    swe.SATURN: ("Сатурн", "♄", "#6B7280"),
    swe.URANUS: ("Уран", "♅", "#06B6D4"),
    swe.NEPTUNE: ("Нептун", "♆", "#3B82F6"),
    swe.PLUTO: ("Плутон", "♇", "#7C3AED"),
}


def get_planet_speed(planet_id: int, dt: datetime) -> float:
    """Получить скорость планеты (градусы/день). Отрицательная = ретроград."""
    jd = datetime_to_julian(dt)
    result = swe.calc_ut(jd, planet_id, swe.FLG_SPEED)
    return result[0][3]  # speed in longitude


def find_retrograde_periods_for_year(year: int) -> List[Dict]:
    """
    Найти все ретроградные периоды планет за год.

    Args:
        year: Год для анализа

    Returns:
        Список ретроградных периодов с датами
    """
    retrograde_periods = []

    for planet_id, (name, symbol, color) in RETROGRADE_PLANETS.items():
        periods = []
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31)

        current_date = start_date
        in_retrograde = False
        retrograde_start = None

        # Проверяем, начался ли год в ретрограде
        initial_speed = get_planet_speed(planet_id, current_date)
        if initial_speed < 0:
            in_retrograde = True
            # Ищем начало этого ретрограда в прошлом году
            search_date = current_date - timedelta(days=1)
            while get_planet_speed(planet_id, search_date) < 0:
                search_date -= timedelta(days=1)
            retrograde_start = search_date + timedelta(days=1)

        # Сканируем весь год
        while current_date <= end_date:
            speed = get_planet_speed(planet_id, current_date)

            if not in_retrograde and speed < 0:
                # Начало ретрограда
                in_retrograde = True
                retrograde_start = current_date
            elif in_retrograde and speed >= 0:
                # Конец ретрограда
                in_retrograde = False
                periods.append({
                    "start": retrograde_start.strftime("%d.%m.%Y"),
                    "end": (current_date - timedelta(days=1)).strftime("%d.%m.%Y"),
                    "start_date": retrograde_start,
                    "end_date": current_date - timedelta(days=1),
                })
                retrograde_start = None

            current_date += timedelta(days=1)

        # Если год закончился в ретрограде
        if in_retrograde and retrograde_start:
            # Ищем конец ретрограда в следующем году
            search_date = end_date + timedelta(days=1)
            while get_planet_speed(planet_id, search_date) < 0:
                search_date += timedelta(days=1)
            periods.append({
                "start": retrograde_start.strftime("%d.%m.%Y"),
                "end": (search_date - timedelta(days=1)).strftime("%d.%m.%Y"),
                "start_date": retrograde_start,
                "end_date": search_date - timedelta(days=1),
            })

        retrograde_periods.append({
            "planet_id": planet_id,
            "name": name,
            "symbol": symbol,
            "color": color,
            "periods": periods,
        })

    return retrograde_periods


def get_current_retrogrades(dt: datetime = None) -> Dict:
    """
    Получить текущий статус ретроградов всех планет.

    Returns:
        Словарь с информацией о текущих ретроградах
    """
    if dt is None:
        dt = datetime.now()

    current_retrogrades = []
    all_planets = []

    for planet_id, (name, symbol, color) in RETROGRADE_PLANETS.items():
        speed = get_planet_speed(planet_id, dt)
        is_retrograde = speed < 0

        planet_info = {
            "name": name,
            "symbol": symbol,
            "color": color,
            "is_retrograde": is_retrograde,
            "speed": round(speed, 4),
        }
        all_planets.append(planet_info)

        if is_retrograde:
            current_retrogrades.append(planet_info)

    return {
        "date": dt.strftime("%d.%m.%Y"),
        "retrograde_count": len(current_retrogrades),
        "current_retrogrades": current_retrogrades,
        "all_planets": all_planets,
    }


def get_retrogrades_info(year: int = None) -> Dict:
    """
    Получить полную информацию о ретроградах на год.

    Args:
        year: Год (по умолчанию текущий)

    Returns:
        Полная информация о ретроградах
    """
    if year is None:
        year = datetime.now().year

    # Текущий статус
    current = get_current_retrogrades()

    # Периоды на год
    periods = find_retrograde_periods_for_year(year)

    # Находим ближайший ретроград
    today = datetime.now().date()
    next_retrograde = None
    nearest_upcoming_date = None

    for planet_data in periods:
        for period in planet_data["periods"]:
            start = period["start_date"].date()
            end = period["end_date"].date()

            # Если сейчас в ретрограде
            if start <= today <= end:
                # Показываем активный ретроград
                if next_retrograde is None or next_retrograde.get("status") != "active":
                    next_retrograde = {
                        "planet": planet_data["name"],
                        "symbol": planet_data["symbol"],
                        "status": "active",
                        "end_date": period["end"],
                        "days_left": (end - today).days,
                    }

            # Если ретроград ещё впереди
            elif start > today:
                if nearest_upcoming_date is None or start < nearest_upcoming_date:
                    nearest_upcoming_date = start
                    # Только если нет активного ретрограда
                    if next_retrograde is None or next_retrograde.get("status") != "active":
                        next_retrograde = {
                            "planet": planet_data["name"],
                            "symbol": planet_data["symbol"],
                            "status": "upcoming",
                            "start_date": period["start"],
                            "days_until": (start - today).days,
                        }

    return {
        "year": year,
        "current": current,
        "periods": periods,
        "next_retrograde": next_retrograde,
    }
