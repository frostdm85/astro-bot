#!/usr/bin/env python3
# coding: utf-8

"""
Клиент Groq API для генерации астрологических прогнозов
Интеграция с системой формул Шестопалова
"""

import logging
import json
import asyncio
from typing import List, Dict, Optional
from functools import wraps

from groq import Groq

from config import GROQ_API_KEY, GROQ_MODEL
from data.formula_meanings import analyze_transit_formula, get_formula_meaning, ALL_FORMULAS

logger = logging.getLogger(__name__)

# Лимит сообщений в истории чата (предотвращает переполнение контекста)
MAX_CHAT_MESSAGES = 15

# Максимальное количество повторных попыток при ошибках API
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1  # Базовая задержка в секундах

# Инициализация клиента Groq
client = Groq(api_key=GROQ_API_KEY)

# ==============================================================================
# СИСТЕМНЫЙ ПРОМПТ ДЛЯ ИНТЕРПРЕТАЦИИ ФОРМУЛ
# ==============================================================================
FORMULA_SYSTEM_PROMPT = """Ты — астролог-консультант. Интерпретируй формулы событий.

ВРЕМЯ В ФОРМУЛАХ:
- Если указано конкретное время (например "с 15:00 — 17:30") — используй его
- Если указано "в течение дня" — это общая тенденция дня, описывай без времени

ЗНАК ФОРМУЛЫ:
- (+) = ПОЗИТИВНО: "хорошее время", "благоприятно"
- (-) = НЕГАТИВНО: "лучше отложить", "будьте осторожнее"

ЗАПРЕЩЕНО:
- Для (-) писать "хорошее время"
- Для (+) писать "проблемы", "сложности"
- Использовать термины: транзит, аспект, дом, формула
- Писать в третьем лице
- Использовать имя пользователя в тексте прогноза
- Говорить "нет указания времени" или "не могу дать прогноз"
- Обобщать или опускать формулы

ОБЯЗАТЕЛЬНО:
- ВСЕГДА обращаться ТОЛЬКО на "Вы" ("у Вас", "Вам", "для Вас")
- НИКОГДА не использовать имя пользователя в тексте прогноза
- ОПИСАТЬ КАЖДУЮ формулу как конкретное событие или ситуацию
- Использовать точные значения из формул (финансы, отношения, творчество, документы и т.д.)
- Давать практические рекомендации на основе формул
- В конце добавить общую оценку дня

СТРУКТУРА ОТВЕТА:
1. Опиши каждую формулу отдельно (что может произойти, в какой сфере)
2. Дай практический совет по каждой формуле
3. Общая оценка дня

ПРИМЕР ХОРОШЕГО ОТВЕТА:
"С 15:00 до 17:30 благоприятное время для финансовых решений — можете заключать сделки или обсуждать зарплату. В течение дня возможны разногласия с близкими по бытовым вопросам — лучше воздержаться от споров о деньгах. На работе всё складывается хорошо для креативных задач. В целом день смешанный: утро продуктивное, вечер требует терпения."
"""

# Старый промпт для чата
ASTRO_SYSTEM_PROMPT = """Ты — профессиональный астролог, специализирующийся на транзитном анализе.

ТВОИ ЗАДАЧИ:
1. Отвечать на вопросы пользователя об астрологии
2. Давать практические рекомендации
3. Описывать влияние планет понятным языком

СТИЛЬ:
- Дружелюбный, но профессиональный
- Без запугивания негативными аспектами
- Краткие и ёмкие формулировки

ВАЖНО:
- ВСЕГДА отвечай на русском языке
- НЕ используй LaTeX разметку
- НЕ давай медицинских или юридических советов"""


# Злые (напряжённые) планеты — соединение с ними даёт негативный аспект
MALEFIC_PLANETS = {'Марс', 'Сатурн', 'Уран', 'Нептун', 'Плутон'}
# Добрые (благоприятные) планеты — соединение с ними даёт позитивный аспект
BENEFIC_PLANETS = {'Солнце', 'Луна', 'Венера', 'Юпитер'}
# Нейтральный — Меркурий (зависит от аспектов)


def is_conjunction_negative(transit_planet: str, natal_planet: str) -> bool:
    """
    Определяет, является ли соединение напряжённым.
    Соединение негативное, если хотя бы одна из планет — злая.
    """
    return transit_planet in MALEFIC_PLANETS or natal_planet in MALEFIC_PLANETS


def extract_formula_meanings(transits: List[Dict]) -> List[Dict]:
    """
    Извлечь значения формул из списка транзитов.

    Args:
        transits: Список транзитов с полями transit_house, transit_rules,
                  natal_house, natal_rules, is_positive, exact_time

    Returns:
        Список найденных значений формул с временем
    """
    results = []

    for tr in transits:
        # Собираем все дома транзитной планеты
        t_houses = [tr.get('transit_house', 0)]
        t_houses.extend(tr.get('transit_rules', []))
        t_houses = [h for h in t_houses if h]

        # Собираем все дома натальной планеты
        n_houses = [tr.get('natal_house', 0)]
        n_houses.extend(tr.get('natal_rules', []))
        n_houses = [h for h in n_houses if h]

        # Определяем природу аспекта
        # Поле называется 'aspect_name' в astro_engine.py
        aspect = tr.get('aspect_name', '').lower()
        transit_planet = tr.get('transit_planet', '')
        natal_planet = tr.get('natal_planet', '')

        if aspect in ['тригон', 'секстиль', 'трин']:
            is_positive = True
            sign = "+"
        elif aspect in ['квадратура', 'оппозиция']:
            is_positive = False
            sign = "-"
        elif aspect in ['соединение']:
            # Соединение: проверяем злые планеты
            if is_conjunction_negative(transit_planet, natal_planet):
                is_positive = False
                sign = "-"
            else:
                is_positive = True
                sign = "+"
        else:
            # Неизвестный аспект — по умолчанию нейтральный/позитивный
            is_positive = True
            sign = "±"

        # Ищем совпадения с формулами
        meanings = analyze_transit_formula(t_houses, n_houses, is_positive)

        # Убираем ссылки типа "(см. также X)"
        cleaned_meanings = []
        for m in meanings:
            # Убираем скобочные ссылки
            clean_m = m.split(" (см.")[0].strip()
            if clean_m and clean_m not in cleaned_meanings:
                cleaned_meanings.append(clean_m)

        if cleaned_meanings:
            # Извлекаем время — поле exact_datetime это объект datetime
            exact_dt = tr.get('exact_datetime')
            if exact_dt:
                # Форматируем время точного аспекта
                end_time = exact_dt.strftime("%H:%M")
                # Вычисляем начало действия (2 часа до точного аспекта)
                start_hour = max(0, exact_dt.hour - 2)
                start_time = f"{start_hour:02d}:00"
                time_range = f"{start_time} — {end_time}"
            else:
                time_range = ""

            results.append({
                'time_range': time_range,
                'transit': tr.get('transit_planet', ''),
                'natal': tr.get('natal_planet', ''),
                'aspect': aspect,
                'sign': sign,
                'meanings': cleaned_meanings
            })

    return results


async def generate_forecast(
    transits_data: str,
    transits_list: List[Dict] = None,
    user_name: str = "",
    forecast_type: str = "daily",
    target_date: str = None
) -> str:
    """
    Генерация астрологического прогноза на основе формул Шестопалова.

    ВАЖНО: Прогноз строится СТРОГО на найденных формулах событий.
    Если формул нет — говорим "нет особых указаний".

    Args:
        transits_data: Отформатированный текст транзитов (для отображения)
        transits_list: Список транзитов (словари) для анализа формул
        user_name: Имя пользователя для персонализации
        forecast_type: Тип прогноза (daily, period, weekly, monthly, date)
        target_date: Целевая дата прогноза

    Returns:
        Текст прогноза
    """
    try:
        # Формируем запрос
        period_names = {
            "daily": "на сегодня",
            "period_3d": "на ближайшие 2-3 дня",
            "period": "на указанный период",
            "weekly": "на неделю",
            "monthly": "на месяц",
            "date": f"на {target_date}" if target_date else "на указанную дату"
        }
        period = period_names.get(forecast_type, "на сегодня")

        # Извлекаем формулы событий если есть транзиты
        formulas_text = ""
        if transits_list:
            formula_results = extract_formula_meanings(transits_list)
            logger.info(f"Формулы для ИИ: {formula_results}")

            if formula_results:
                formulas_text = "\n\nФОРМУЛЫ СОБЫТИЙ (используй ТОЛЬКО их для прогноза):\n"
                for fr in formula_results:
                    time_range = fr.get('time_range', '')
                    if time_range:
                        time_display = f"с {time_range}"
                    else:
                        time_display = "в течение дня"

                    meanings_str = "; ".join(fr['meanings'])
                    formulas_text += f"• {time_display} ({fr['sign']}): {meanings_str}\n"
            else:
                formulas_text = "\n\nФОРМУЛЫ СОБЫТИЙ: не найдено значимых формул.\nОтвет: 'Сегодня нет особых указаний, день проходит в обычном режиме.'"

        # Персонализация
        greeting = f"для {user_name}" if user_name else ""

        user_prompt = f"""Прогноз {period} {greeting}.
{formulas_text}

ВАЖНО:
1. (+) = позитивно, хорошее время
2. (-) = НЕГАТИВНО, лучше отложить, быть осторожнее
3. Если указано время (например "с 15:00 — 17:30") — используй его
4. Если указано "в течение дня" — описывай как общую тенденцию дня

Напиши прогноз 2-4 предложения на основе формул выше. НЕ говори что "времени нет" — используй то что дано."""

        # Retry logic для устойчивости к временным ошибкам API
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": FORMULA_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=1024,
                    temperature=0.6
                )
                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # Повторяем только при rate limit или временных ошибках
                if 'rate' in error_str or '429' in error_str or '503' in error_str or 'timeout' in error_str:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)  # Экспоненциальная задержка
                    logger.warning(f"Groq API ошибка (попытка {attempt + 1}/{MAX_RETRIES}), повтор через {delay}с: {e}")
                    await asyncio.sleep(delay)
                else:
                    raise  # Для других ошибок не повторяем

        # Если все попытки исчерпаны
        logger.error(f"Ошибка генерации прогноза после {MAX_RETRIES} попыток: {last_error}")
        raise last_error

    except Exception as e:
        logger.error(f"Ошибка генерации прогноза: {e}")
        raise


async def chat_with_context(
    messages: List[Dict],
    forecast_context: str = "",
    user_name: str = ""
) -> str:
    """
    Чат с контекстом прогноза (для вопросов пользователя)

    Args:
        messages: История сообщений [{role, content}, ...]
        forecast_context: Текстовый контекст прогноза (опционально)
        user_name: Имя пользователя для персонализации

    Returns:
        Ответ ассистента
    """
    try:
        # Дополняем системный промпт контекстом
        system_content = ASTRO_SYSTEM_PROMPT
        if forecast_context:
            system_content += f"\n\nКОНТЕКСТ ПРОГНОЗА:\n{forecast_context}"
        if user_name:
            system_content += f"\n\nИмя пользователя: {user_name}"

        # Ограничиваем историю сообщений для предотвращения переполнения контекста
        limited_messages = messages[-MAX_CHAT_MESSAGES:] if len(messages) > MAX_CHAT_MESSAGES else messages
        full_messages = [{"role": "system", "content": system_content}] + limited_messages

        # Retry logic
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=full_messages,
                    max_tokens=1024,
                    temperature=0.7
                )
                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if 'rate' in error_str or '429' in error_str or '503' in error_str or 'timeout' in error_str:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    logger.warning(f"Groq API ошибка в чате (попытка {attempt + 1}/{MAX_RETRIES}), повтор через {delay}с: {e}")
                    await asyncio.sleep(delay)
                else:
                    raise

        logger.error(f"Ошибка чата после {MAX_RETRIES} попыток: {last_error}")
        raise last_error

    except Exception as e:
        logger.error(f"Ошибка чата: {e}")
        raise


# ==============================================================================
# ВОПРОСЫ ПО ПРОГНОЗУ
# ==============================================================================

FORECAST_QUESTION_PROMPT = """Ты астролог. Ответь на вопрос пользователя по прогнозу.

Прогноз на {date}:
{forecast_context}

Правила: отвечай кратко (2-3 предложения), на основе прогноза, обращайся на вы."""


async def ask_forecast(
    question: str,
    date_str: str,
    forecast_context: str,
    user_name: str = ""
) -> str:
    """
    Ответить на вопрос пользователя по прогнозу конкретного дня.

    Args:
        question: Вопрос пользователя
        date_str: Дата прогноза (dd.mm.yyyy)
        forecast_context: Текст прогноза на этот день
        user_name: Имя пользователя

    Returns:
        Ответ на вопрос
    """
    try:
        # Очищаем контекст от потенциально проблемных символов
        clean_context = (forecast_context or "Прогноз не загружен").replace("\n", " ").strip()
        if len(clean_context) > 1000:
            clean_context = clean_context[:1000] + "..."

        system_prompt = FORECAST_QUESTION_PROMPT.format(
            date=date_str,
            forecast_context=clean_context
        )

        if user_name:
            system_prompt += f" Имя: {user_name}."

        # Retry logic
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question}
                    ],
                    max_tokens=512,
                    temperature=0.6
                )
                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # Обработка 403 как временной ошибки
                if 'rate' in error_str or '429' in error_str or '503' in error_str or 'timeout' in error_str or '403' in error_str:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    logger.warning(f"Groq API ошибка в ask_forecast (попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                    await asyncio.sleep(delay)
                else:
                    raise

        # Если все попытки провалились, возвращаем fallback ответ
        logger.error(f"Ошибка ask_forecast после {MAX_RETRIES} попыток: {last_error}")
        return "Извините, сервис временно недоступен. Попробуйте задать вопрос чуть позже."

    except Exception as e:
        logger.error(f"Ошибка ask_forecast: {e}")
        # Fallback ответ при любой ошибке
        return "Извините, не удалось обработать ваш вопрос. Попробуйте переформулировать или спросить позже."


def transcribe_audio(audio_path: str) -> str:
    """
    Транскрибация голосового сообщения (синхронная функция)

    Для асинхронного использования вызывать через asyncio.to_thread()

    Args:
        audio_path: Путь к файлу аудио

    Returns:
        Распознанный текст
    """
    try:
        with open(audio_path, 'rb') as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="ru"
            )
        return response.text

    except Exception as e:
        logger.error(f"Ошибка транскрибации: {e}")
        raise


def analyze_question(question: str, natal_data: Dict) -> str:
    """
    Анализ произвольного вопроса пользователя

    Args:
        question: Вопрос пользователя
        natal_data: Натальные данные

    Returns:
        Ответ астролога
    """
    try:
        user_prompt = f"""Пользователь спрашивает: "{question}"

НАТАЛЬНЫЕ ДАННЫЕ:
- Дата рождения: {natal_data.get('birth_date')}
- Место рождения: {natal_data.get('birth_place')}

Ответь на вопрос с астрологической точки зрения, учитывая натальную карту пользователя."""

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": ASTRO_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1024,
            temperature=0.7
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Ошибка анализа вопроса: {e}")
        raise
