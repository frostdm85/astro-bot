#!/usr/bin/env python3
# coding: utf-8

"""
Обработчики вопросов пользователей к AI-астрологу
"""

import logging
import asyncio
import os
import time as time_module
from datetime import datetime, date

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import QUESTIONS_PER_DAY
from database.models import User, Forecast, Conversation
from services.groq_client import chat_with_context, transcribe_audio
from services.tts_service import text_to_speech

logger = logging.getLogger(__name__)

# FSM состояния для вопросов
user_question_states = {}  # {user_id: {"state": "waiting_question", "forecast_id": None}}


# ============== ТЕКСТЫ ==============

ASK_QUESTION_TEXT = """💬 <b>Задайте ваш вопрос</b>

Уточните любой аспект прогноза или задайте вопрос по натальной карте.

Осталось вопросов: <b>{remaining}/{total}</b>"""

ASK_ABOUT_FORECAST_TEXT = """💬 <b>Вопрос по прогнозу на {date}</b>

Вы можете уточнить любой аспект этого прогноза.

Осталось вопросов: <b>{remaining}/{total}</b>

Отправьте текстовое или голосовое сообщение."""

AI_THINKING_TEXT = """🤔 <b>Обрабатываю ваш вопрос...</b>

<i>Анализирую астрологический контекст...</i>"""

AI_ANSWER_TEXT = """🤖 <b>Ответ астролога:</b>

{answer}

━━━━━━━━━━━━━━━━━━━━━━━━
Осталось вопросов: {remaining}/{total}"""

NO_QUESTIONS_LEFT_TEXT = """❌ <b>Лимит вопросов исчерпан</b>

Вы использовали все {total} вопросов на сегодня.

Лимит обновится завтра в 00:00.

Хотите продлить подписку с увеличенным лимитом?"""


# ============== КЛАВИАТУРЫ ==============

def get_question_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура в режиме вопросов"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_main")]
    ])


def get_answer_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура после ответа"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Ещё вопрос", callback_data="ask_question"),
            InlineKeyboardButton("🔊 Озвучить", callback_data="voice_answer")
        ],
        [InlineKeyboardButton("🔮 Главное меню", callback_data="back_main")]
    ])


def get_no_questions_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура когда закончились вопросы"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Продлить подписку", callback_data="payment_extend")],
        [InlineKeyboardButton("🔮 Главное меню", callback_data="back_main")]
    ])


# ============== FSM ==============

def set_question_state(user_id: int, state: str, forecast_id: int = None):
    """Установить состояние пользователя с timestamp для TTL"""
    user_question_states[user_id] = {
        "state": state,
        "forecast_id": forecast_id,
        "last_answer": None,
        "created_at": time_module.time()
    }


def get_question_state(user_id: int) -> dict:
    """Получить состояние пользователя"""
    return user_question_states.get(user_id, {"state": None, "forecast_id": None})


def clear_question_state(user_id: int):
    """Очистить состояние"""
    if user_id in user_question_states:
        del user_question_states[user_id]


def set_last_answer(user_id: int, answer: str):
    """Сохранить последний ответ для озвучки"""
    if user_id in user_question_states:
        user_question_states[user_id]["last_answer"] = answer


def get_last_answer(user_id: int) -> str:
    """Получить последний ответ"""
    state = user_question_states.get(user_id, {})
    return state.get("last_answer", "")


# ============== ОБРАБОТЧИКИ ==============

async def handle_ask_question(client: Client, callback: CallbackQuery, user: User):
    """Обработка нажатия 'Задать вопрос'"""
    remaining = user.get_questions_remaining()

    if remaining <= 0:
        await callback.answer("Лимит вопросов исчерпан!", show_alert=True)
        await callback.message.edit_text(
            NO_QUESTIONS_LEFT_TEXT.format(total=QUESTIONS_PER_DAY),
            reply_markup=get_no_questions_keyboard()
        )
        return

    # Устанавливаем состояние ожидания вопроса
    set_question_state(user.telegram_id, "waiting_question")

    await callback.answer()
    await callback.message.edit_text(
        ASK_QUESTION_TEXT.format(remaining=remaining, total=QUESTIONS_PER_DAY),
        reply_markup=get_question_keyboard()
    )


async def handle_ask_about_forecast(client: Client, callback: CallbackQuery, user: User, forecast_id: int):
    """Обработка нажатия 'Задать вопрос по прогнозу'"""
    remaining = user.get_questions_remaining()

    if remaining <= 0:
        await callback.answer("Лимит вопросов исчерпан!", show_alert=True)
        await callback.message.edit_text(
            NO_QUESTIONS_LEFT_TEXT.format(total=QUESTIONS_PER_DAY),
            reply_markup=get_no_questions_keyboard()
        )
        return

    try:
        forecast = Forecast.get_by_id(forecast_id)
        date_str = forecast.target_date.strftime("%d.%m.%Y")
    except Forecast.DoesNotExist:
        date_str = "—"

    # Устанавливаем состояние с привязкой к прогнозу
    set_question_state(user.telegram_id, "waiting_question", forecast_id)

    await callback.answer()
    await callback.message.edit_text(
        ASK_ABOUT_FORECAST_TEXT.format(date=date_str, remaining=remaining, total=QUESTIONS_PER_DAY),
        reply_markup=get_question_keyboard()
    )


async def handle_voice_answer(client: Client, callback: CallbackQuery, user: User):
    """Озвучивание последнего ответа AI"""
    answer = get_last_answer(user.telegram_id)

    if not answer:
        await callback.answer("Нет ответа для озвучивания", show_alert=True)
        return

    await callback.answer("Озвучиваю...")

    try:
        audio_path = await text_to_speech(answer)

        if audio_path:
            await callback.message.reply_voice(audio_path)
            # Удаляем временный файл
            if os.path.exists(audio_path):
                os.remove(audio_path)
        else:
            await callback.answer("Не удалось озвучить ответ", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка озвучки ответа: {e}")
        await callback.answer("Ошибка озвучивания", show_alert=True)


async def process_text_question(client: Client, message: Message, user: User):
    """Обработка текстового вопроса"""
    state = get_question_state(user.telegram_id)

    if state.get("state") != "waiting_question":
        return False  # Не в режиме вопросов

    # Проверяем лимит
    remaining = user.get_questions_remaining()
    if remaining <= 0:
        await message.reply(
            NO_QUESTIONS_LEFT_TEXT.format(total=QUESTIONS_PER_DAY),
            reply_markup=get_no_questions_keyboard()
        )
        clear_question_state(user.telegram_id)
        return True

    question = message.text.strip()
    if not question:
        return True

    # Показываем, что обрабатываем
    thinking_msg = await message.reply(AI_THINKING_TEXT)

    try:
        # Получаем контекст прогноза если есть
        forecast_context = ""
        forecast_id = state.get("forecast_id")
        if forecast_id:
            try:
                forecast = Forecast.get_by_id(forecast_id)
                forecast_context = f"Контекст прогноза на {forecast.target_date.strftime('%d.%m.%Y')}:\n{forecast.forecast_text[:1000]}"
            except Forecast.DoesNotExist:
                pass

        # Получаем историю диалога
        conversation = get_or_create_conversation(user, forecast_id)
        messages = conversation.get_messages()

        # Добавляем вопрос пользователя
        messages.append({"role": "user", "content": question})

        # Получаем ответ от AI
        answer = await chat_with_context(
            messages=messages,
            forecast_context=forecast_context,
            user_name=user.display_name
        )

        if not answer:
            answer = "Извините, не удалось получить ответ. Попробуйте переформулировать вопрос."

        # Сохраняем в историю
        messages.append({"role": "assistant", "content": answer})
        conversation.set_messages(messages)
        conversation.save()

        # Увеличиваем счётчик вопросов
        user.use_question()
        remaining = user.get_questions_remaining()

        # Сохраняем ответ для озвучки
        set_last_answer(user.telegram_id, answer)

        # Отправляем ответ
        await thinking_msg.edit_text(
            AI_ANSWER_TEXT.format(answer=answer, remaining=remaining, total=QUESTIONS_PER_DAY),
            reply_markup=get_answer_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка обработки вопроса: {e}")
        await thinking_msg.edit_text(
            f"❌ Произошла ошибка: {str(e)}\n\nПопробуйте ещё раз.",
            reply_markup=get_question_keyboard()
        )

    return True


async def process_voice_question(client: Client, message: Message, user: User):
    """Обработка голосового вопроса"""
    state = get_question_state(user.telegram_id)

    if state.get("state") != "waiting_question":
        return False  # Не в режиме вопросов

    # Проверяем лимит
    remaining = user.get_questions_remaining()
    if remaining <= 0:
        await message.reply(
            NO_QUESTIONS_LEFT_TEXT.format(total=QUESTIONS_PER_DAY),
            reply_markup=get_no_questions_keyboard()
        )
        clear_question_state(user.telegram_id)
        return True

    # Показываем, что обрабатываем
    thinking_msg = await message.reply("🎤 <b>Распознаю голосовое сообщение...</b>")

    try:
        # Скачиваем голосовое сообщение
        voice_path = await message.download()

        # Проверяем, что файл скачался
        if not voice_path or not os.path.exists(voice_path):
            await thinking_msg.edit_text(
                "❌ Не удалось загрузить голосовое сообщение. Попробуйте ещё раз.",
                reply_markup=get_question_keyboard()
            )
            return True

        # Транскрибируем (синхронная функция, запускаем в отдельном потоке)
        question = await asyncio.to_thread(transcribe_audio, voice_path)

        # Удаляем временный файл
        if os.path.exists(voice_path):
            os.remove(voice_path)

        if not question:
            await thinking_msg.edit_text(
                "❌ Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.",
                reply_markup=get_question_keyboard()
            )
            return True

        # Показываем распознанный текст
        await thinking_msg.edit_text(
            f"🎤 <b>Распознано:</b> {question}\n\n⏳ Обрабатываю вопрос..."
        )

        # Получаем контекст прогноза
        forecast_context = ""
        forecast_id = state.get("forecast_id")
        if forecast_id:
            try:
                forecast = Forecast.get_by_id(forecast_id)
                forecast_context = f"Контекст прогноза на {forecast.target_date.strftime('%d.%m.%Y')}:\n{forecast.forecast_text[:1000]}"
            except Forecast.DoesNotExist:
                pass

        # Получаем историю диалога
        conversation = get_or_create_conversation(user, forecast_id)
        messages = conversation.get_messages()

        # Добавляем вопрос
        messages.append({"role": "user", "content": question})

        # Получаем ответ
        answer = await chat_with_context(
            messages=messages,
            forecast_context=forecast_context,
            user_name=user.display_name
        )

        if not answer:
            answer = "Извините, не удалось получить ответ. Попробуйте переформулировать вопрос."

        # Сохраняем в историю
        messages.append({"role": "assistant", "content": answer})
        conversation.set_messages(messages)
        conversation.save()

        # Увеличиваем счётчик
        user.use_question()
        remaining = user.get_questions_remaining()

        # Сохраняем для озвучки
        set_last_answer(user.telegram_id, answer)

        # Отправляем ответ
        await thinking_msg.edit_text(
            AI_ANSWER_TEXT.format(answer=answer, remaining=remaining, total=QUESTIONS_PER_DAY),
            reply_markup=get_answer_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка обработки голосового вопроса: {e}")
        await thinking_msg.edit_text(
            f"❌ Произошла ошибка: {str(e)}\n\nПопробуйте ещё раз.",
            reply_markup=get_question_keyboard()
        )

    return True


# ============== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==============

def get_or_create_conversation(user: User, forecast_id: int = None) -> Conversation:
    """Получить или создать диалог"""
    try:
        # Ищем существующий диалог за сегодня
        today = date.today()
        conversation = Conversation.select().where(
            Conversation.user == user,
            Conversation.created_at >= datetime.combine(today, datetime.min.time())
        ).order_by(Conversation.created_at.desc()).first()

        if conversation:
            return conversation

    except Exception:
        pass

    # Создаём новый
    return Conversation.create(
        user=user,
        forecast=forecast_id if forecast_id else None,
        messages="[]"
    )


def register_handlers(app: Client):
    """Регистрация обработчиков вопросов"""
    from pyrogram.handlers import MessageHandler

    logger.info("Регистрация обработчиков questions.py...")

    # Обработчик текстовых сообщений в режиме вопросов
    async def text_message_handler(client: Client, message: Message):
        try:
            user = User.get_by_id(message.from_user.id)
        except User.DoesNotExist:
            return

        # Проверяем, в режиме ли вопросов
        if await process_text_question(client, message, user):
            return

    # Обработчик голосовых сообщений
    async def voice_message_handler(client: Client, message: Message):
        try:
            user = User.get_by_id(message.from_user.id)
        except User.DoesNotExist:
            return

        # Проверяем, в режиме ли вопросов
        if await process_voice_question(client, message, user):
            return

    # Регистрируем в группе 3, чтобы обрабатывать после start.py и admin.py
    text_filter = filters.text & filters.private & ~filters.command(["start", "help", "admin", "webapp", "forecast", "settings", "support"])
    app.add_handler(MessageHandler(text_message_handler, text_filter), group=3)
    app.add_handler(MessageHandler(voice_message_handler, filters.voice & filters.private), group=3)

    logger.info("Все обработчики questions.py зарегистрированы")
