#!/usr/bin/env python3
# coding: utf-8

"""
Text-to-Speech сервис на основе Edge TTS
На основе gpt-umnik + документация edge-tts (https://github.com/rany2/edge-tts)
"""

import asyncio
import tempfile
import logging
import os

import edge_tts

logger = logging.getLogger(__name__)

# Доступные голоса
VOICES = {
    'ru_male': 'ru-RU-DmitryNeural',       # Русский мужской (основной)
    'ru_female': 'ru-RU-SvetlanaNeural',   # Русский женский
    'en_male': 'en-US-GuyNeural',          # Английский мужской
    'en_female': 'en-US-JennyNeural',      # Английский женский
}

# Голос по умолчанию для астро-бота
DEFAULT_VOICE = 'ru_male'


async def text_to_speech(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz"
) -> str:
    """
    Конвертировать текст в речь

    Args:
        text: Текст для озвучки
        voice: Ключ голоса из VOICES
        rate: Скорость речи (например, "-10%", "+20%")
        pitch: Высота голоса

    Returns:
        Путь к временному MP3 файлу
    """
    try:
        voice_name = VOICES.get(voice, VOICES[DEFAULT_VOICE])

        # Очистка текста от markdown и эмодзи для лучшей озвучки
        clean_text = _clean_text_for_tts(text)

        # Создаём временный файл
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            output_path = f.name

        # Генерируем аудио через Edge TTS
        communicate = edge_tts.Communicate(
            text=clean_text,
            voice=voice_name,
            rate=rate,
            pitch=pitch
        )
        await communicate.save(output_path)

        logger.info(f"TTS: создан файл {output_path} ({len(clean_text)} символов)")
        return output_path

    except Exception as e:
        logger.error(f"Ошибка TTS: {e}")
        raise


def sync_text_to_speech(
    text: str,
    voice: str = DEFAULT_VOICE
) -> str:
    """
    Синхронная обёртка для text_to_speech

    Безопасно работает как из синхронного контекста,
    так и при вызове из async функций через to_thread().
    """
    import concurrent.futures

    try:
        # Пытаемся получить текущий running loop
        loop = asyncio.get_running_loop()
        # Если мы здесь — значит loop запущен, нужен новый в отдельном потоке
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, text_to_speech(text, voice))
            return future.result(timeout=60)  # Таймаут 60 секунд
    except RuntimeError:
        # Нет running loop — можно использовать asyncio.run() напрямую
        return asyncio.run(text_to_speech(text, voice))


async def get_available_voices(language: str = "ru") -> list:
    """
    Получить список доступных голосов для языка

    Args:
        language: Код языка (ru, en, etc.)

    Returns:
        Список голосов
    """
    try:
        voices = await edge_tts.list_voices()
        return [
            v for v in voices
            if v['Locale'].startswith(language)
        ]
    except Exception as e:
        logger.error(f"Ошибка получения голосов: {e}")
        return []


def _clean_text_for_tts(text: str) -> str:
    """
    Очистка текста для лучшей озвучки

    - Удаляет markdown разметку
    - Заменяет символы планет на слова
    - Убирает лишние пробелы
    """
    import re

    # Замена символов планет на названия
    planet_replacements = {
        '☉': 'Солнце',
        '☽': 'Луна',
        '☿': 'Меркурий',
        '♀': 'Венера',
        '♂': 'Марс',
        '♃': 'Юпитер',
        '♄': 'Сатурн',
        '♅': 'Уран',
        '♆': 'Нептун',
        '♇': 'Плутон',
    }

    for symbol, name in planet_replacements.items():
        text = text.replace(symbol, name)

    # Удаление markdown
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'\*(.*?)\*', r'\1', text)       # *italic*
    text = re.sub(r'`(.*?)`', r'\1', text)         # `code`
    text = re.sub(r'━+', '', text)                  # разделители
    text = re.sub(r'#{1,6}\s*', '', text)          # заголовки

    # Удаление лишних пробелов и переносов
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()


def cleanup_audio_file(file_path: str):
    """Удалить временный аудиофайл"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f"Удалён временный файл: {file_path}")
    except Exception as e:
        logger.warning(f"Не удалось удалить файл {file_path}: {e}")
