#!/usr/bin/env python3
# coding: utf-8

"""
Админ-панель для Астро-бота
"""

import logging
import asyncio
import time as time_module
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID, SUBSCRIPTION_DAYS
from database.models import (
    User, Subscription, Forecast, SupportTicket, SupportMessage,
    get_stats, db
)
from services.consent_service import get_users_for_broadcast, get_consent_statistics, delete_user_data
from services.geocoder import quick_geocode, format_coordinates
from utils.keyboards import (
    get_admin_main_keyboard,
    get_admin_users_filter_keyboard,
    get_admin_users_list_keyboard,
    get_admin_user_card_keyboard,
    get_admin_edit_user_keyboard,
    get_admin_subscription_keyboard,
    get_admin_broadcast_audience_keyboard,
    get_admin_broadcast_confirm_keyboard,
    get_admin_support_keyboard,
    get_admin_ticket_keyboard,
    get_cancel_keyboard,
    get_confirm_city_keyboard,
    get_add_user_confirm_keyboard
)

logger = logging.getLogger(__name__)

# FSM состояния админа
admin_states: Dict[int, Dict[str, Any]] = {}


def set_admin_state(admin_id: int, state: str, data: dict = None):
    """Установить состояние админа с timestamp для TTL"""
    admin_states[admin_id] = {
        "state": state,
        "data": data or {},
        "created_at": time_module.time()
    }


def get_admin_state(admin_id: int) -> Optional[Dict]:
    """Получить состояние админа"""
    return admin_states.get(admin_id)


def clear_admin_state(admin_id: int):
    """Очистить состояние админа"""
    if admin_id in admin_states:
        del admin_states[admin_id]


# ============== ТЕКСТЫ ==============

ADMIN_MAIN_TEXT = """👑 <b>Админ-панель</b>


📊 <b>Статистика:</b>
• Всего пользователей: {total_users}
• С натальными данными: {with_data}
• Без данных: {without_data}
• Активных подписок: {active_subs}
• Истекает в 3 дня: {expiring_soon}
• Истекших: {expired}

📋 <b>Согласия (152-ФЗ):</b>
• Согласие ПД: {pd_consented}/{total_users}
• Подписаны на рассылку: {marketing_consented}
• Отказались: {marketing_refused}
• Заблокировали бота: {blocked_users}
"""

USER_CARD_TEXT = """👤 <b>{name}</b>


📱 Telegram: {username} (ID: <code>{telegram_id}</code>)
📅 Зарегистрирован: {created_at}


🔮 <b>Натальные данные:</b>
📅 Рождение: {birth_date}
📍 Место рождения: {birth_place} {birth_coords}
🏠 Проживание: {residence} {residence_coords}
🕐 Часовой пояс: {timezone}


💳 Подписка: {sub_status}
💰 Всего оплачено: {total_paid}


📊 <b>Активность:</b>
• Вопросов сегодня: {questions_today}/10
• Всего прогнозов: {forecasts_count}
• Последний вход: {last_seen}"""

SUB_MANAGEMENT_TEXT = """💳 <b>Подписка: {name}</b>

Текущий статус: {status}
{expires_info}"""


# ============== ХЕЛПЕРЫ ==============

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id == ADMIN_ID


def format_user_card(user: User) -> str:
    """Форматирование карточки пользователя"""
    username = f"@{user.username}" if user.username else "нет"
    created = user.created_at.strftime("%d.%m.%Y") if user.created_at else "—"

    birth_date = user.birth_datetime_str
    birth_place = user.birth_place or "Не указано"
    birth_coords = f"({user.birth_lat:.4f}, {user.birth_lon:.4f})" if user.birth_lat else ""

    residence = user.residence_place or "Не указано"
    residence_coords = f"({user.residence_lat:.4f}, {user.residence_lon:.4f})" if user.residence_lat else ""

    timezone = user.birth_tz or user.residence_tz or "Europe/Moscow"

    sub = user.get_subscription()
    if sub and sub.status in ['active', 'expiring_soon']:
        sub_status = f"✅ Активна до {sub.expires_at.strftime('%d.%m.%Y')}"
    else:
        sub_status = "❌ Неактивна"

    # Подсчёт оплат
    total_paid = Subscription.select().where(
        Subscription.user == user,
        Subscription.amount.is_null(False)
    ).count()
    total_paid_str = f"{total_paid} оплат" if total_paid > 0 else "0 ₽"

    # Прогнозы
    forecasts_count = Forecast.select().where(Forecast.user == user).count()

    last_seen = user.updated_at.strftime("%d.%m.%Y, %H:%M") if user.updated_at else "—"

    return USER_CARD_TEXT.format(
        name=user.display_name,
        username=username,
        telegram_id=user.telegram_id,
        created_at=created,
        birth_date=birth_date,
        birth_place=birth_place,
        birth_coords=birth_coords,
        residence=residence,
        residence_coords=residence_coords,
        timezone=timezone,
        sub_status=sub_status,
        total_paid=total_paid_str,
        questions_today=user.questions_today,
        forecasts_count=forecasts_count,
        last_seen=last_seen
    )


def get_users_by_filter(filter_type: str) -> list:
    """Получить пользователей по фильтру"""
    now = datetime.now()
    three_days = now + timedelta(days=3)

    if filter_type == "all":
        return list(User.select().order_by(User.created_at.desc()))

    elif filter_type == "active":
        # Пользователи с активной подпиской
        active_user_ids = (
            Subscription.select(Subscription.user)
            .where(
                Subscription.status.in_(['active', 'expiring_soon']),
                Subscription.expires_at > now
            )
        )
        return list(User.select().where(User.telegram_id.in_(active_user_ids)))

    elif filter_type == "expired":
        # Пользователи с истёкшей подпиской
        expired_user_ids = (
            Subscription.select(Subscription.user)
            .where(Subscription.status == 'expired')
        )
        return list(User.select().where(User.telegram_id.in_(expired_user_ids)))

    elif filter_type == "expiring":
        # Истекает в 3 дня
        expiring_user_ids = (
            Subscription.select(Subscription.user)
            .where(
                Subscription.status.in_(['active', 'expiring_soon']),
                Subscription.expires_at <= three_days,
                Subscription.expires_at > now
            )
        )
        return list(User.select().where(User.telegram_id.in_(expiring_user_ids)))

    elif filter_type == "nodata":
        return list(User.select().where(User.natal_data_complete == False))

    return []


def get_filter_counts() -> dict:
    """Подсчёт пользователей по фильтрам"""
    now = datetime.now()
    three_days = now + timedelta(days=3)

    total = User.select().count()
    nodata = User.select().where(User.natal_data_complete == False).count()

    active = Subscription.select().where(
        Subscription.status.in_(['active', 'expiring_soon']),
        Subscription.expires_at > now
    ).count()

    expiring = Subscription.select().where(
        Subscription.status.in_(['active', 'expiring_soon']),
        Subscription.expires_at <= three_days,
        Subscription.expires_at > now
    ).count()

    expired = Subscription.select().where(Subscription.status == 'expired').count()

    return {
        "all": total,
        "active": active,
        "expired": expired,
        "expiring": expiring,
        "nodata": nodata
    }


# ============== ОБРАБОТЧИКИ ==============

async def admin_command(client: Client, message: Message):
    """Команда /admin"""
    if not is_admin(message.from_user.id):
        return

    stats = get_stats()
    consent_stats = get_consent_statistics()
    stats.update(consent_stats)  # Добавляем статистику согласий
    support_count = SupportTicket.select().where(SupportTicket.status == "open").count()

    await message.reply(
        ADMIN_MAIN_TEXT.format(**stats),
        reply_markup=get_admin_main_keyboard(support_count)
    )


async def show_admin_panel(client: Client, callback: CallbackQuery):
    """Показать админ-панель по кнопке из главного меню"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    stats = get_stats()
    consent_stats = get_consent_statistics()
    stats.update(consent_stats)
    support_count = SupportTicket.select().where(SupportTicket.status == "open").count()

    await callback.answer()
    await callback.message.edit_text(
        ADMIN_MAIN_TEXT.format(**stats),
        reply_markup=get_admin_main_keyboard(support_count)
    )


async def admin_callback(client: Client, callback: CallbackQuery):
    """Обработчик callback админ-панели"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    data = callback.data
    admin_id = callback.from_user.id

    # === ГЛАВНОЕ МЕНЮ ===

    if data == "adm_main":
        clear_admin_state(admin_id)
        stats = get_stats()
        consent_stats = get_consent_statistics()
        stats.update(consent_stats)
        support_count = SupportTicket.select().where(SupportTicket.status == "open").count()
        await callback.answer()
        await callback.message.edit_text(
            ADMIN_MAIN_TEXT.format(**stats),
            reply_markup=get_admin_main_keyboard(support_count)
        )

    elif data == "adm_close":
        clear_admin_state(admin_id)
        await callback.answer()
        await callback.message.delete()

    elif data == "adm_cancel":
        clear_admin_state(admin_id)
        await callback.answer("Отменено")
        stats = get_stats()
        support_count = SupportTicket.select().where(SupportTicket.status == "open").count()
        await callback.message.edit_text(
            ADMIN_MAIN_TEXT.format(**stats),
            reply_markup=get_admin_main_keyboard(support_count)
        )

    # === ПОЛЬЗОВАТЕЛИ ===

    elif data == "adm_users":
        clear_admin_state(admin_id)
        users = get_users_by_filter("all")
        counts = get_filter_counts()
        await callback.answer()

        if not users:
            await callback.message.edit_text(
                "👥 <b>Пользователи</b>\n\nСписок пуст.",
                reply_markup=get_admin_main_keyboard(0)
            )
            return

        await callback.message.edit_text(
            "👥 <b>Пользователи</b>\n\n🔍 Отправьте имя, @username или ID для поиска.",
            reply_markup=get_admin_users_list_keyboard(users, 0, 5, "all")
        )

    elif data == "adm_users_filters":
        counts = get_filter_counts()
        await callback.answer()
        await callback.message.edit_text(
            "👥 <b>Фильтры пользователей</b>",
            reply_markup=get_admin_users_filter_keyboard("all", counts)
        )

    elif data.startswith("adm_users_filter_"):
        filter_type = data.replace("adm_users_filter_", "")
        users = get_users_by_filter(filter_type)
        counts = get_filter_counts()
        set_admin_state(admin_id, "users_list", {"filter": filter_type, "page": 0})
        await callback.answer()
        await callback.message.edit_text(
            f"👥 <b>Пользователи</b> — фильтр: {filter_type}",
            reply_markup=get_admin_users_list_keyboard(users, 0, 5, filter_type)
        )

    elif data.startswith("adm_users_page_"):
        page = int(data.replace("adm_users_page_", ""))
        state = get_admin_state(admin_id)
        filter_type = state["data"].get("filter", "all") if state else "all"
        users = get_users_by_filter(filter_type)
        set_admin_state(admin_id, "users_list", {"filter": filter_type, "page": page})
        await callback.answer()
        await callback.message.edit_reply_markup(
            reply_markup=get_admin_users_list_keyboard(users, page, 5, filter_type)
        )

    elif data.startswith("adm_user_"):
        user_id = int(data.replace("adm_user_", ""))
        try:
            user = User.get_by_id(user_id)
            await callback.answer()
            await callback.message.edit_text(
                format_user_card(user),
                reply_markup=get_admin_user_card_keyboard(user_id)
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    # === РЕДАКТИРОВАНИЕ ПОЛЬЗОВАТЕЛЯ ===

    elif data.startswith("adm_edit_user_"):
        user_id = int(data.replace("adm_edit_user_", ""))
        try:
            user = User.get_by_id(user_id)
            user_data = {
                "birth_date": user.birth_date.strftime("%d.%m.%Y") if user.birth_date else "Не указано",
                "birth_time": user.birth_time.strftime("%H:%M:%S") if user.birth_time else "Не указано",
                "birth_place": user.birth_place or "Не указано",
                "residence_place": user.residence_place or "Не указано",
                "first_name": user.first_name or "Не указано"
            }
            await callback.answer()
            await callback.message.edit_text(
                f"✏️ <b>Редактирование: {user.display_name}</b>\n\nВыберите, что изменить:",
                reply_markup=get_admin_edit_user_keyboard(user_id, user_data)
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    elif data.startswith("adm_edit_birth_date_"):
        user_id = int(data.replace("adm_edit_birth_date_", ""))
        set_admin_state(admin_id, "edit_birth_date", {"user_id": user_id})
        await callback.answer()
        await callback.message.edit_text(
            "📅 <b>Введите новую дату рождения</b>\n\nФормат: ДД.ММ.ГГГГ\nПример: 15.03.1985",
            reply_markup=get_cancel_keyboard()
        )

    elif data.startswith("adm_edit_birth_time_"):
        user_id = int(data.replace("adm_edit_birth_time_", ""))
        set_admin_state(admin_id, "edit_birth_time", {"user_id": user_id})
        await callback.answer()
        await callback.message.edit_text(
            "⏰ <b>Введите новое время рождения</b>\n\nФормат: ЧЧ:ММ\nПример: 14:30",
            reply_markup=get_cancel_keyboard()
        )

    elif data.startswith("adm_edit_birth_place_"):
        user_id = int(data.replace("adm_edit_birth_place_", ""))
        set_admin_state(admin_id, "edit_birth_place", {"user_id": user_id})
        await callback.answer()
        await callback.message.edit_text(
            "📍 <b>Введите новое место рождения</b>\n\nПример: Москва",
            reply_markup=get_cancel_keyboard()
        )

    elif data.startswith("adm_edit_residence_"):
        user_id = int(data.replace("adm_edit_residence_", ""))
        set_admin_state(admin_id, "edit_residence", {"user_id": user_id})
        await callback.answer()
        await callback.message.edit_text(
            "🏠 <b>Введите новое место проживания</b>\n\nПример: Санкт-Петербург",
            reply_markup=get_cancel_keyboard()
        )

    elif data.startswith("adm_edit_name_"):
        user_id = int(data.replace("adm_edit_name_", ""))
        set_admin_state(admin_id, "edit_name", {"user_id": user_id})
        await callback.answer()
        await callback.message.edit_text(
            "👤 <b>Введите новое имя</b>\n\nПример: Иван Иванов",
            reply_markup=get_cancel_keyboard()
        )

    # === УПРАВЛЕНИЕ ПОДПИСКОЙ ===

    elif data.startswith("adm_sub_") and not data.startswith("adm_sub_extend_") and not data.startswith("adm_sub_set_date_") and not data.startswith("adm_sub_free_") and not data.startswith("adm_sub_cancel_"):
        user_id = int(data.replace("adm_sub_", ""))
        try:
            user = User.get_by_id(user_id)
            sub = user.get_subscription()
            has_active = sub and sub.status in ['active', 'expiring_soon']

            if has_active:
                status = f"✅ Активна"
                expires_info = f"Действует до: {sub.expires_at.strftime('%d.%m.%Y')}\nОсталось дней: {sub.days_left}"
            else:
                status = "❌ Неактивна"
                expires_info = ""

            await callback.answer()
            await callback.message.edit_text(
                SUB_MANAGEMENT_TEXT.format(
                    name=user.display_name,
                    status=status,
                    expires_info=expires_info
                ),
                reply_markup=get_admin_subscription_keyboard(user_id, has_active)
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    elif data.startswith("adm_sub_extend_"):
        user_id = int(data.replace("adm_sub_extend_", ""))
        try:
            user = User.get_by_id(user_id)
            sub = user.get_subscription()
            if not sub:
                sub = Subscription.create_for_user(user)
            sub.activate(SUBSCRIPTION_DAYS)
            await callback.answer(f"Подписка продлена на {SUBSCRIPTION_DAYS} дней")

            # Уведомляем пользователя
            try:
                await client.send_message(
                    user_id,
                    f"🎉 Ваша подписка продлена!\n\n✅ Активна до: {sub.expires_at.strftime('%d.%m.%Y')}"
                )
            except:
                pass

            # Обновляем сообщение
            await callback.message.edit_text(
                format_user_card(user),
                reply_markup=get_admin_user_card_keyboard(user_id)
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    elif data.startswith("adm_sub_free_"):
        user_id = int(data.replace("adm_sub_free_", ""))
        try:
            user = User.get_by_id(user_id)
            sub = Subscription.create_for_user(user)
            sub.activate(SUBSCRIPTION_DAYS)
            await callback.answer("Подписка активирована бесплатно")

            try:
                await client.send_message(
                    user_id,
                    f"🎁 Вам активирована подписка!\n\n✅ Активна до: {sub.expires_at.strftime('%d.%m.%Y')}"
                )
            except:
                pass

            await callback.message.edit_text(
                format_user_card(user),
                reply_markup=get_admin_user_card_keyboard(user_id)
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    elif data.startswith("adm_sub_cancel_"):
        user_id = int(data.replace("adm_sub_cancel_", ""))
        try:
            user = User.get_by_id(user_id)
            sub = user.get_subscription()
            if sub:
                sub.cancel()
                await callback.answer("Подписка отменена")
            else:
                await callback.answer("Подписка не найдена", show_alert=True)

            await callback.message.edit_text(
                format_user_card(user),
                reply_markup=get_admin_user_card_keyboard(user_id)
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    elif data.startswith("adm_sub_set_date_"):
        user_id = int(data.replace("adm_sub_set_date_", ""))
        set_admin_state(admin_id, "set_sub_date", {"user_id": user_id})
        await callback.answer()
        await callback.message.edit_text(
            "📅 <b>Установка даты окончания подписки</b>\n\n"
            "Введите дату в формате ДД.ММ.ГГГГ\n\n"
            "Пример: 31.12.2025",
            reply_markup=get_cancel_keyboard()
        )

    # === ДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ===

    elif data == "adm_add_user":
        set_admin_state(admin_id, "add_user_id", {"step": 1})
        await callback.answer()
        await callback.message.edit_text(
            "➕ <b>Добавление клиента</b>\n\n<b>Шаг 1 из 6: Идентификация</b>\n\n"
            "Введите Telegram ID или @username нового клиента.\n\n"
            "💡 Попросите клиента написать боту /start, чтобы получить его ID автоматически.",
            reply_markup=get_cancel_keyboard()
        )

    elif data == "adm_add_save":
        state = get_admin_state(admin_id)
        if not state or "new_user" not in state["data"]:
            await callback.answer("Данные не найдены", show_alert=True)
            return

        new_user_data = state["data"]["new_user"]
        try:
            user = User.get_by_id(new_user_data["telegram_id"])
        except User.DoesNotExist:
            user = User.create(telegram_id=new_user_data["telegram_id"])

        # Обновляем данные
        user.first_name = new_user_data.get("first_name", "")
        user.birth_date = new_user_data.get("birth_date")
        user.birth_time = new_user_data.get("birth_time")
        user.birth_place = new_user_data.get("birth_place")
        user.birth_lat = new_user_data.get("birth_lat")
        user.birth_lon = new_user_data.get("birth_lon")
        user.birth_tz = new_user_data.get("birth_tz")
        user.residence_place = new_user_data.get("residence_place")
        user.residence_lat = new_user_data.get("residence_lat")
        user.residence_lon = new_user_data.get("residence_lon")
        user.residence_tz = new_user_data.get("residence_tz", "Europe/Moscow")
        user.natal_data_complete = True
        user.save()

        clear_admin_state(admin_id)
        await callback.answer("Клиент добавлен!")
        await callback.message.edit_text(
            format_user_card(user),
            reply_markup=get_admin_user_card_keyboard(user.telegram_id)
        )

    elif data == "adm_add_edit":
        # Вернуться к началу добавления пользователя
        state = get_admin_state(admin_id)
        if state and "new_user" in state.get("data", {}):
            # Сохраняем существующие данные и начинаем с начала
            set_admin_state(admin_id, "add_user_id", {"step": 1})
        else:
            set_admin_state(admin_id, "add_user_id", {"step": 1})

        await callback.answer()
        await callback.message.edit_text(
            "➕ <b>Редактирование клиента</b>\n\n<b>Шаг 1 из 6: Идентификация</b>\n\n"
            "Введите Telegram ID или @username клиента.",
            reply_markup=get_cancel_keyboard()
        )

    elif data == "city_confirm":
        # Подтверждение города (используется в add user flow)
        state = get_admin_state(admin_id)
        if not state:
            await callback.answer("Сессия истекла", show_alert=True)
            return
        # Продолжаем текущий flow - город уже сохранён
        await callback.answer("✅ Город подтверждён")

    elif data == "city_retry":
        # Повторный поиск города
        state = get_admin_state(admin_id)
        if not state:
            await callback.answer("Сессия истекла", show_alert=True)
            return

        state_name = state.get("state", "")
        if state_name == "add_user_residence":
            await callback.answer()
            await callback.message.edit_text(
                "➕ <b>Добавление клиента</b>\n\n<b>Шаг 6 из 6: Место проживания</b>\n\n"
                "Введите другой город проживания.\n\nПример: Санкт-Петербург",
                reply_markup=get_cancel_keyboard()
            )
        elif state_name == "add_user_birth_place":
            await callback.answer()
            await callback.message.edit_text(
                "➕ <b>Добавление клиента</b>\n\n<b>Шаг 5 из 6: Место рождения</b>\n\n"
                "Введите другой город рождения.\n\nПример: Москва",
                reply_markup=get_cancel_keyboard()
            )
        else:
            await callback.answer("Введите название города заново")

    # === РАССЫЛКА ===

    elif data == "adm_broadcast":
        # Показываем количество подписанных на рассылку (152-ФЗ, 38-ФЗ)
        users_with_consent = get_users_for_broadcast().count()
        total = User.select().count()

        set_admin_state(admin_id, "broadcast_text", {})
        await callback.answer()
        await callback.message.edit_text(
            f"📢 <b>Рассылка</b>\n\n"
            f"⚠️ Рассылка отправляется ТОЛЬКО пользователям, "
            f"которые дали согласие на рассылку (152-ФЗ, 38-ФЗ).\n\n"
            f"📊 Получателей: <b>{users_with_consent}</b> из {total}\n\n"
            "Введите текст сообщения.\n\n"
            "💡 Поддерживается HTML-форматирование.",
            reply_markup=get_cancel_keyboard()
        )

    elif data.startswith("adm_bcast_"):
        audience = data.replace("adm_bcast_", "")

        if audience == "send":
            # Отправка рассылки — ТОЛЬКО подписанным на рассылку (152-ФЗ, 38-ФЗ)
            state = get_admin_state(admin_id)
            if not state or "broadcast" not in state["data"]:
                await callback.answer("Данные рассылки не найдены", show_alert=True)
                return

            bcast_data = state["data"]["broadcast"]
            # Получаем ТОЛЬКО пользователей с согласием на рассылку
            users = list(get_users_for_broadcast())
            text = bcast_data["text"]

            await callback.answer("Начинаю рассылку...")
            await callback.message.edit_text(f"📢 Рассылка в процессе... (0/{len(users)})")

            success = 0
            failed = 0
            blocked = 0
            for i, user in enumerate(users):
                try:
                    await client.send_message(user.telegram_id, text)
                    success += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    error_str = str(e).lower()
                    if "blocked" in error_str or "deactivated" in error_str or "403" in error_str:
                        # Пользователь заблокировал бота
                        from services.consent_service import mark_bot_blocked
                        mark_bot_blocked(user)
                        blocked += 1
                    else:
                        failed += 1
                    logger.error(f"Ошибка рассылки {user.telegram_id}: {e}")

                # Обновляем прогресс каждые 10 сообщений
                if (i + 1) % 10 == 0:
                    try:
                        await callback.message.edit_text(
                            f"📢 Рассылка в процессе... ({i + 1}/{len(users)})"
                        )
                    except:
                        pass

            clear_admin_state(admin_id)
            stats = get_stats()
            consent_stats = get_consent_statistics()
            stats.update(consent_stats)
            await callback.message.edit_text(
                f"✅ <b>Рассылка завершена</b>\n\n"
                f"📊 Статистика:\n"
                f"• Отправлено: {success}\n"
                f"• Заблокировали: {blocked}\n"
                f"• Ошибок: {failed}",
                reply_markup=get_admin_main_keyboard(0)
            )

        elif audience == "edit":
            set_admin_state(admin_id, "broadcast_text", get_admin_state(admin_id)["data"])
            await callback.answer()
            await callback.message.edit_text(
                "📢 <b>Рассылка</b>\n\nВведите новый текст сообщения:",
                reply_markup=get_cancel_keyboard()
            )

    # === МАССОВЫЙ ЗАПРОС СОГЛАСИЯ НА РАССЫЛКУ ===

    elif data == "adm_marketing_request":
        # Подсчёт пользователей по категориям
        all_count = User.select().where(
            (User.pd_consent == True) &
            (User.marketing_consent.is_null()) &
            (User.is_bot_blocked == False) &
            (User.marketing_asked_count < 3)
        ).count()

        new_count = User.select().where(
            (User.pd_consent == True) &
            (User.marketing_consent.is_null()) &
            (User.is_bot_blocked == False) &
            (User.marketing_asked_count == 0)
        ).count()

        asked_count = User.select().where(
            (User.pd_consent == True) &
            (User.marketing_consent.is_null()) &
            (User.is_bot_blocked == False) &
            (User.marketing_asked_count > 0) &
            (User.marketing_asked_count < 3)
        ).count()

        from utils.keyboards import get_admin_marketing_audience_keyboard
        await callback.answer()
        await callback.message.edit_text(
            "📬 <b>Массовый запрос согласия на рассылку</b>\n\n"
            "Выберите аудиторию для отправки запроса:\n\n"
            f"👥 Все без согласия: <b>{all_count}</b>\n"
            f"🆕 Новые (ни разу не спрашивали): <b>{new_count}</b>\n"
            f"🔄 Уже спрашивали (1-2 раза): <b>{asked_count}</b>\n\n"
            "⚠️ Пользователям, отказавшимся 3 раза, запрос не отправится.",
            reply_markup=get_admin_marketing_audience_keyboard(all_count, new_count, asked_count)
        )

    elif data.startswith("adm_marketing_audience_"):
        audience = data.replace("adm_marketing_audience_", "")
        set_admin_state(admin_id, "marketing_request_text", {"audience": audience})

        audience_names = {
            "all": "Все без согласия",
            "new": "Новые пользователи",
            "asked": "Уже спрашивали"
        }

        from utils.keyboards import get_admin_marketing_text_keyboard
        await callback.answer()
        await callback.message.edit_text(
            f"📬 <b>Массовый запрос согласия</b>\n\n"
            f"Аудитория: <b>{audience_names.get(audience, audience)}</b>\n\n"
            "Введите текст сообщения для запроса на рассылку.\n"
            "Или нажмите кнопку для использования стандартного текста.",
            reply_markup=get_admin_marketing_text_keyboard()
        )

    elif data == "adm_marketing_send":
        state = get_admin_state(admin_id)
        if not state or state["state"] != "marketing_request_text":
            await callback.answer("Ошибка: состояние не найдено", show_alert=True)
            return

        audience = state["data"].get("audience", "all")
        custom_text = state["data"].get("text")

        # Получаем пользователей по аудитории
        base_query = User.select().where(
            (User.pd_consent == True) &
            (User.marketing_consent.is_null()) &
            (User.is_bot_blocked == False) &
            (User.marketing_asked_count < 3)
        )

        if audience == "new":
            users = list(base_query.where(User.marketing_asked_count == 0))
        elif audience == "asked":
            users = list(base_query.where(User.marketing_asked_count > 0))
        else:
            users = list(base_query)

        total = len(users)

        if total == 0:
            clear_admin_state(admin_id)
            await callback.answer("Нет пользователей для отправки", show_alert=True)
            stats = get_stats()
            consent_stats = get_consent_statistics()
            stats.update(consent_stats)
            await callback.message.edit_text(
                ADMIN_MAIN_TEXT.format(**stats),
                reply_markup=get_admin_main_keyboard(0)
            )
            return

        await callback.answer("Начинаю отправку...")
        await callback.message.edit_text(f"📬 Отправка запросов... 0/{total}")

        # Текст сообщения
        if custom_text:
            message_text = custom_text
        else:
            message_text = (
                "⭐ <b>Подпишитесь на новости!</b>\n\n"
                "Бесплатные функции, акции и новые возможности — узнавайте первыми!\n\n"
                "Вы можете отписаться в любой момент через Настройки → Документы."
            )

        from utils.keyboards import get_marketing_consent_keyboard
        from services.consent_service import mark_marketing_asked, mark_bot_blocked

        success = 0
        failed = 0
        blocked = 0

        for i, user in enumerate(users):
            try:
                # Определяем текст кнопки "Нет" в зависимости от попытки
                if user.marketing_asked_count >= 2:
                    no_btn_text = "❌ Нет, спасибо"
                else:
                    no_btn_text = "❌ Не сейчас"

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Подписаться", callback_data="consent_marketing_yes"),
                        InlineKeyboardButton(no_btn_text, callback_data="consent_marketing_no")
                    ]
                ])

                await client.send_message(
                    user.telegram_id,
                    message_text,
                    reply_markup=keyboard
                )

                # Отмечаем что показали запрос
                mark_marketing_asked(user)
                success += 1

                await asyncio.sleep(0.05)

            except Exception as e:
                error_str = str(e).lower()
                if "blocked" in error_str or "deactivated" in error_str or "403" in error_str:
                    mark_bot_blocked(user)
                    blocked += 1
                else:
                    failed += 1
                logger.error(f"Ошибка отправки маркетинга {user.telegram_id}: {e}")

            # Обновляем прогресс
            if (i + 1) % 10 == 0 or i == total - 1:
                try:
                    await callback.message.edit_text(f"📬 Отправка запросов... {i + 1}/{total}")
                except:
                    pass

        clear_admin_state(admin_id)

        blocked_info = f"\n🚫 Заблокировали бота: <b>{blocked}</b>" if blocked > 0 else ""

        await callback.message.edit_text(
            f"✅ <b>Массовая отправка завершена!</b>\n\n"
            f"📨 Отправлено: <b>{success}</b>\n"
            f"❌ Не доставлено: <b>{failed}</b>{blocked_info}",
            reply_markup=get_admin_main_keyboard(0)
        )

    elif data == "adm_marketing_cancel":
        clear_admin_state(admin_id)
        stats = get_stats()
        consent_stats = get_consent_statistics()
        stats.update(consent_stats)
        await callback.answer()
        await callback.message.edit_text(
            ADMIN_MAIN_TEXT.format(**stats),
            reply_markup=get_admin_main_keyboard(0)
        )

    # === ПОДДЕРЖКА ===

    elif data == "adm_support":
        tickets = list(SupportTicket.select().where(
            SupportTicket.status == "open"
        ).order_by(SupportTicket.updated_at.desc()))
        await callback.answer()
        await callback.message.edit_text(
            "💬 <b>Обращения в поддержку</b>",
            reply_markup=get_admin_support_keyboard(tickets, "new")
        )

    elif data.startswith("adm_support_"):
        filter_type = data.replace("adm_support_", "")
        status_map = {"new": "open", "progress": "answered", "closed": "closed"}
        status = status_map.get(filter_type, "open")
        tickets = list(SupportTicket.select().where(
            SupportTicket.status == status
        ).order_by(SupportTicket.updated_at.desc()))
        await callback.answer()
        await callback.message.edit_text(
            "💬 <b>Обращения в поддержку</b>",
            reply_markup=get_admin_support_keyboard(tickets, filter_type)
        )

    elif data.startswith("adm_ticket_") and not data.startswith("adm_ticket_close_"):
        ticket_id = int(data.replace("adm_ticket_", ""))
        try:
            ticket = SupportTicket.get_by_id(ticket_id)
            messages = list(ticket.messages.order_by(SupportMessage.created_at))

            text = f"💬 <b>Тикет #{ticket.id}</b>\n\n"
            text += f"👤 {ticket.user.display_name} (@{ticket.user.username or 'нет'})\n"
            text += f"📅 Создан: {ticket.created_at.strftime('%d.%m.%Y, %H:%M')}\n"
            text += f"📊 Статус: {ticket.status}\n\n"

            for msg in messages[-10:]:
                sender = "👤 Пользователь" if msg.sender_type == "user" else "👑 Админ"
                time = msg.created_at.strftime("%H:%M")
                text += f"[{time}] {sender}:\n{msg.message_text}\n\n"

            text += "Чтобы ответить, отправьте сообщение."

            set_admin_state(admin_id, "reply_ticket", {"ticket_id": ticket_id})
            await callback.answer()
            await callback.message.edit_text(
                text,
                reply_markup=get_admin_ticket_keyboard(ticket_id, ticket.user.telegram_id)
            )
        except SupportTicket.DoesNotExist:
            await callback.answer("Тикет не найден", show_alert=True)

    elif data.startswith("adm_ticket_close_"):
        ticket_id = int(data.replace("adm_ticket_close_", ""))
        try:
            ticket = SupportTicket.get_by_id(ticket_id)
            ticket.status = "closed"
            ticket.save()
            await callback.answer("Тикет закрыт")
            # Возврат к списку
            tickets = list(SupportTicket.select().where(
                SupportTicket.status == "open"
            ).order_by(SupportTicket.updated_at.desc()))
            await callback.message.edit_text(
                "💬 <b>Обращения в поддержку</b>",
                reply_markup=get_admin_support_keyboard(tickets, "new")
            )
        except SupportTicket.DoesNotExist:
            await callback.answer("Тикет не найден", show_alert=True)

    # === ДЕЙСТВИЯ С ПОЛЬЗОВАТЕЛЕМ ===

    elif data.startswith("adm_msg_"):
        user_id = int(data.replace("adm_msg_", ""))
        set_admin_state(admin_id, "send_message", {"user_id": user_id})
        await callback.answer()
        await callback.message.edit_text(
            "📨 <b>Написать пользователю</b>\n\nВведите текст сообщения:",
            reply_markup=get_cancel_keyboard()
        )

    elif data.startswith("adm_send_forecast_"):
        user_id = int(data.replace("adm_send_forecast_", ""))
        await callback.answer("Генерирую прогноз...")

        try:
            user = User.get_by_id(user_id)
            if not user.natal_data_complete:
                await callback.message.edit_text(
                    "❌ У пользователя не заполнены натальные данные!",
                    reply_markup=get_admin_user_card_keyboard(user_id)
                )
                return

            # Импортируем и вызываем генерацию прогноза
            from handlers.forecast import send_daily_forecast

            await callback.message.edit_text("⏳ Генерация прогноза...")
            success = await send_daily_forecast(client, user)

            if success:
                await callback.message.edit_text(
                    f"✅ Прогноз отправлен пользователю {user.display_name}",
                    reply_markup=get_admin_user_card_keyboard(user_id)
                )
            else:
                await callback.message.edit_text(
                    "❌ Ошибка генерации прогноза",
                    reply_markup=get_admin_user_card_keyboard(user_id)
                )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка отправки прогноза: {e}")
            await callback.message.edit_text(
                f"❌ Ошибка: {e}",
                reply_markup=get_admin_user_card_keyboard(user_id)
            )

    elif data.startswith("adm_history_"):
        user_id = int(data.replace("adm_history_", ""))
        try:
            user = User.get_by_id(user_id)
            forecasts = Forecast.select().where(
                Forecast.user == user
            ).order_by(Forecast.created_at.desc()).limit(10)

            if not forecasts.count():
                await callback.answer("Нет истории прогнозов", show_alert=True)
                return

            history_text = f"📋 <b>История прогнозов для {user.display_name}</b>\n\n"
            for fc in forecasts:
                date_str = fc.target_date.strftime("%d.%m.%Y")
                created_str = fc.created_at.strftime("%d.%m %H:%M")
                history_text += f"📅 {date_str} ({fc.forecast_type}) — {created_str}\n"

            await callback.answer()
            await callback.message.edit_text(
                history_text,
                reply_markup=get_admin_user_card_keyboard(user_id)
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    elif data.startswith("adm_delete_"):
        user_id = int(data.replace("adm_delete_", ""))
        try:
            user = User.get_by_id(user_id)
            # Очищаем данные пользователя (152-ФЗ: запись User и consent_log сохраняются)
            delete_user_data(user)
            await callback.answer("Данные пользователя очищены")

            # Возврат к списку
            users = get_users_by_filter("all")
            await callback.message.edit_text(
                "👥 <b>Пользователи</b>",
                reply_markup=get_admin_users_list_keyboard(users, 0, 5, "all")
            )
        except User.DoesNotExist:
            await callback.answer("Пользователь не найден", show_alert=True)

    # === СТАТИСТИКА ===

    elif data == "adm_stats":
        stats = get_stats()
        text = f"""📊 <b>Детальная статистика</b>


👥 <b>Пользователи:</b>
• Всего: {stats['total_users']}
• С натальными данными: {stats['with_data']}
• Без данных: {stats['without_data']}


💳 <b>Подписки:</b>
• Активных: {stats['active_subs']}
• Истекает в 3 дня: {stats['expiring_soon']}
• Истекших: {stats['expired']}


💰 <b>Финансы:</b>
• Всего оплат: {stats['total_revenue']}"""

        await callback.answer()
        await callback.message.edit_text(
            text,
            reply_markup=get_admin_main_keyboard(0)
        )


async def admin_text_handler(client: Client, message: Message):
    """Обработка текстовых сообщений админа"""
    if not is_admin(message.from_user.id):
        return

    state = get_admin_state(message.from_user.id)
    if not state:
        return

    text = message.text.strip()
    state_name = state["state"]
    data = state["data"]

    # === РЕДАКТИРОВАНИЕ ПОЛЬЗОВАТЕЛЯ ===

    if state_name == "edit_birth_date":
        try:
            birth_date = datetime.strptime(text, "%d.%m.%Y").date()
            user = User.get_by_id(data["user_id"])
            user.birth_date = birth_date
            user.save()
            clear_admin_state(message.from_user.id)
            await message.reply(
                f"✅ Дата рождения обновлена: {text}\n\n" + format_user_card(user),
                reply_markup=get_admin_user_card_keyboard(user.telegram_id)
            )
        except ValueError:
            await message.reply("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

    elif state_name == "edit_birth_time":
        try:
            from datetime import time
            parts = text.split(":")
            if len(parts) == 3:
                birth_time = time(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                birth_time = time(int(parts[0]), int(parts[1]), 0)
            user = User.get_by_id(data["user_id"])
            user.birth_time = birth_time
            user.save()
            clear_admin_state(message.from_user.id)
            await message.reply(
                f"✅ Время рождения обновлено: {birth_time.strftime('%H:%M:%S')}\n\n" + format_user_card(user),
                reply_markup=get_admin_user_card_keyboard(user.telegram_id)
            )
        except (ValueError, IndexError):
            await message.reply("❌ Неверный формат времени. Используйте ЧЧ:ММ:СС или ЧЧ:ММ")

    elif state_name == "edit_birth_place":
        geo = quick_geocode(text)
        if not geo:
            await message.reply(
                f"❌ Город «{text}» не найден.\n\nПопробуйте ввести название иначе или укажите страну (например: Москва, Россия)",
                reply_markup=get_cancel_keyboard()
            )
            return

        user = User.get_by_id(data["user_id"])
        user.birth_place = geo.city
        user.birth_lat = geo.latitude
        user.birth_lon = geo.longitude
        user.birth_tz = geo.timezone
        user.save()

        clear_admin_state(message.from_user.id)
        await message.reply(
            f"✅ Место рождения обновлено:\n\n"
            f"📍 {geo.display_name}\n"
            f"🌐 {format_coordinates(geo.latitude, geo.longitude)}\n"
            f"🕐 {geo.timezone}\n\n" + format_user_card(user),
            reply_markup=get_admin_user_card_keyboard(user.telegram_id)
        )

    elif state_name == "edit_residence":
        geo = quick_geocode(text)
        if not geo:
            await message.reply(
                f"❌ Город «{text}» не найден.\n\nПопробуйте ввести название иначе или укажите страну (например: Москва, Россия)",
                reply_markup=get_cancel_keyboard()
            )
            return

        user = User.get_by_id(data["user_id"])
        user.residence_place = geo.city
        user.residence_lat = geo.latitude
        user.residence_lon = geo.longitude
        user.residence_tz = geo.timezone
        user.save()

        clear_admin_state(message.from_user.id)
        await message.reply(
            f"✅ Место проживания обновлено:\n\n"
            f"🏠 {geo.display_name}\n"
            f"🌐 {format_coordinates(geo.latitude, geo.longitude)}\n"
            f"🕐 {geo.timezone}\n\n" + format_user_card(user),
            reply_markup=get_admin_user_card_keyboard(user.telegram_id)
        )

    elif state_name == "edit_name":
        user = User.get_by_id(data["user_id"])
        user.first_name = text
        user.save()
        clear_admin_state(message.from_user.id)
        await message.reply(
            f"✅ Имя обновлено: {text}\n\n" + format_user_card(user),
            reply_markup=get_admin_user_card_keyboard(user.telegram_id)
        )

    elif state_name == "set_sub_date":
        try:
            expires_date = datetime.strptime(text, "%d.%m.%Y")
            user = User.get_by_id(data["user_id"])
            sub = user.get_subscription()
            if not sub:
                sub = Subscription.create_for_user(user)

            sub.expires_at = expires_date
            sub.started_at = sub.started_at or datetime.now()
            sub.status = "active"
            sub.save()

            clear_admin_state(message.from_user.id)
            await message.reply(
                f"✅ Дата подписки установлена: {text}\n\n" + format_user_card(user),
                reply_markup=get_admin_user_card_keyboard(user.telegram_id)
            )
        except ValueError:
            await message.reply("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

    # === ДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ===

    elif state_name == "add_user_id":
        # Шаг 1: ID или username
        try:
            if text.startswith("@"):
                # Поиск по username (упрощённо)
                await message.reply("❌ Введите числовой Telegram ID")
                return

            telegram_id = int(text)
            data["new_user"] = {"telegram_id": telegram_id}
            set_admin_state(message.from_user.id, "add_user_name", data)
            await message.reply(
                "➕ <b>Добавление клиента</b>\n\n<b>Шаг 2 из 6: Имя</b>\n\n"
                "Введите имя клиента (как обращаться в прогнозах).\n\nПример: Иван Иванов",
                reply_markup=get_cancel_keyboard()
            )
        except ValueError:
            await message.reply("❌ Введите корректный Telegram ID (число)")

    elif state_name == "add_user_name":
        data["new_user"]["first_name"] = text
        set_admin_state(message.from_user.id, "add_user_birth_date", data)
        await message.reply(
            "➕ <b>Добавление клиента</b>\n\n<b>Шаг 3 из 6: Дата рождения</b>\n\n"
            "Введите дату рождения.\n\nФормат: ДД.ММ.ГГГГ\nПример: 15.03.1985",
            reply_markup=get_cancel_keyboard()
        )

    elif state_name == "add_user_birth_date":
        try:
            birth_date = datetime.strptime(text, "%d.%m.%Y").date()
            data["new_user"]["birth_date"] = birth_date
            set_admin_state(message.from_user.id, "add_user_birth_time", data)
            await message.reply(
                "➕ <b>Добавление клиента</b>\n\n<b>Шаг 4 из 6: Время рождения</b>\n\n"
                "Введите точное время рождения.\n\nФормат: ЧЧ:ММ:СС или ЧЧ:ММ\nПример: 14:30:45 или 14:30\n\n"
                "⚠️ Точность времени критична для расчёта домов!",
                reply_markup=get_cancel_keyboard()
            )
        except ValueError:
            await message.reply("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

    elif state_name == "add_user_birth_time":
        try:
            from datetime import time
            parts = text.split(":")
            if len(parts) == 3:
                birth_time = time(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                birth_time = time(int(parts[0]), int(parts[1]), 0)
            data["new_user"]["birth_time"] = birth_time
            set_admin_state(message.from_user.id, "add_user_birth_place", data)
            await message.reply(
                "➕ <b>Добавление клиента</b>\n\n<b>Шаг 5 из 6: Место рождения</b>\n\n"
                "Введите город рождения.\n\nПример: Москва\n\n"
                "Система автоматически определит координаты.",
                reply_markup=get_cancel_keyboard()
            )
        except (ValueError, IndexError):
            await message.reply("❌ Неверный формат времени. Используйте ЧЧ:ММ:СС или ЧЧ:ММ")

    elif state_name == "add_user_birth_place":
        geo = quick_geocode(text)
        if not geo:
            await message.reply(
                f"❌ Город «{text}» не найден.\n\nПопробуйте ввести название иначе или укажите страну (например: Москва, Россия)",
                reply_markup=get_cancel_keyboard()
            )
            return

        data["new_user"]["birth_place"] = geo.city
        data["new_user"]["birth_lat"] = geo.latitude
        data["new_user"]["birth_lon"] = geo.longitude
        data["new_user"]["birth_tz"] = geo.timezone
        set_admin_state(message.from_user.id, "add_user_residence", data)
        await message.reply(
            f"✅ Место рождения определено:\n\n"
            f"📍 {geo.display_name}\n"
            f"🌐 {format_coordinates(geo.latitude, geo.longitude)}\n"
            f"🕐 {geo.timezone}\n\n"
            "➕ <b>Добавление клиента</b>\n\n<b>Шаг 6 из 6: Место проживания</b>\n\n"
            "Введите текущий город проживания.\n\nПример: Санкт-Петербург",
            reply_markup=get_cancel_keyboard()
        )

    elif state_name == "add_user_residence":
        geo = quick_geocode(text)
        if not geo:
            await message.reply(
                f"❌ Город «{text}» не найден.\n\nПопробуйте ввести название иначе или укажите страну (например: Москва, Россия)",
                reply_markup=get_cancel_keyboard()
            )
            return

        data["new_user"]["residence_place"] = geo.city
        data["new_user"]["residence_lat"] = geo.latitude
        data["new_user"]["residence_lon"] = geo.longitude
        data["new_user"]["residence_tz"] = geo.timezone

        # Показываем подтверждение
        new_user = data["new_user"]
        confirm_text = f"""✅ <b>Проверьте данные клиента:</b>

👤 {new_user['first_name']}
📱 Telegram ID: {new_user['telegram_id']}

📅 Рождение: {new_user['birth_date'].strftime('%d.%m.%Y')}, {new_user['birth_time'].strftime('%H:%M:%S')}
📍 Место рождения: {new_user['birth_place']} ({new_user['birth_lat']:.4f}, {new_user['birth_lon']:.4f})
   Часовой пояс: {new_user['birth_tz']}
🏠 Проживание: {geo.city} ({geo.latitude:.4f}, {geo.longitude:.4f})
   Часовой пояс: {geo.timezone}

Всё верно?"""

        set_admin_state(message.from_user.id, "add_user_confirm", data)
        await message.reply(confirm_text, reply_markup=get_add_user_confirm_keyboard())

    # === РАССЫЛКА ===

    elif state_name == "broadcast_text":
        data["broadcast"] = {"text": text}
        set_admin_state(message.from_user.id, "broadcast_confirm", data)

        # Показываем количество подписанных на рассылку
        users_with_consent = get_users_for_broadcast().count()

        preview = f"""📢 <b>Предпросмотр рассылки</b>


{text}


👥 Получатели: <b>{users_with_consent}</b> (с согласием на рассылку)"""

        await message.reply(preview, reply_markup=get_admin_broadcast_confirm_keyboard())

    # === КАСТОМНЫЙ ТЕКСТ ДЛЯ МАССОВОГО ЗАПРОСА СОГЛАСИЯ ===

    elif state_name == "marketing_request_text":
        data["text"] = text
        set_admin_state(message.from_user.id, "marketing_request_text", data)

        audience = data.get("audience", "all")
        audience_names = {
            "all": "Все без согласия",
            "new": "Новые пользователи",
            "asked": "Уже спрашивали"
        }

        # Подсчитываем аудиторию
        base_query = User.select().where(
            (User.pd_consent == True) &
            (User.marketing_consent.is_null()) &
            (User.is_bot_blocked == False) &
            (User.marketing_asked_count < 3)
        )

        if audience == "new":
            count = base_query.where(User.marketing_asked_count == 0).count()
        elif audience == "asked":
            count = base_query.where(User.marketing_asked_count > 0).count()
        else:
            count = base_query.count()

        preview = f"""📬 <b>Предпросмотр запроса согласия</b>

Аудитория: <b>{audience_names.get(audience, audience)}</b>
Получателей: <b>{count}</b>

<b>Текст:</b>
{text}"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Отправить", callback_data="adm_marketing_send"),
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"adm_marketing_audience_{audience}")
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="adm_marketing_cancel")]
        ])

        await message.reply(preview, reply_markup=keyboard)

    # === ОТВЕТ В ТИКЕТ ===

    elif state_name == "reply_ticket":
        ticket_id = data["ticket_id"]
        try:
            ticket = SupportTicket.get_by_id(ticket_id)

            # Сохраняем ответ
            SupportMessage.create(
                ticket=ticket,
                sender_type="admin",
                sender_id=message.from_user.id,
                message_text=text
            )

            ticket.status = "answered"
            ticket.save()

            # Отправляем пользователю
            try:
                await client.send_message(
                    ticket.user.telegram_id,
                    f"💬 <b>Ответ от поддержки:</b>\n\n{text}"
                )
            except:
                pass

            clear_admin_state(message.from_user.id)
            await message.reply("✅ Ответ отправлен")
        except SupportTicket.DoesNotExist:
            await message.reply("❌ Тикет не найден")

    # === СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЮ ===

    elif state_name == "send_message":
        user_id = data["user_id"]
        try:
            await client.send_message(user_id, text)
            clear_admin_state(message.from_user.id)
            await message.reply("✅ Сообщение отправлено")
        except Exception as e:
            await message.reply(f"❌ Ошибка отправки: {e}")


def register_handlers(app: Client):
    """Регистрация обработчиков админки"""
    from pyrogram.handlers import MessageHandler, CallbackQueryHandler

    logger.info("Регистрация обработчиков admin.py...")

    app.add_handler(MessageHandler(admin_command, filters.command("admin") & filters.private))
    app.add_handler(CallbackQueryHandler(admin_callback, filters.regex(r"^(adm_|city_confirm|city_retry)")))
    # Обработчик текста админа в группе 2, чтобы не конфликтовать с другими
    app.add_handler(MessageHandler(admin_text_handler, filters.text & filters.private & filters.user(ADMIN_ID)), group=2)

    logger.info("Все обработчики admin.py зарегистрированы")
