#!/usr/bin/env python3
# coding: utf-8

"""
Клавиатуры для Астро-бота
"""

from datetime import datetime, date, timedelta
from typing import Optional, List
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import ADMIN_USERNAME, SUBSCRIPTION_PRICE, ADMIN_ID, WEBAPP_URL


# ============== ПОЛЬЗОВАТЕЛЬСКИЕ КЛАВИАТУРЫ ==============

def get_welcome_keyboard(has_natal_data: bool = False, user_id: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура приветствия для нового пользователя без данных"""
    buttons = [
        [InlineKeyboardButton(
            "👨‍💻 Связаться с астрологом",
            url=f"https://t.me/{ADMIN_USERNAME}"
        )],
        [InlineKeyboardButton(
            "ℹ️ Как это работает?",
            callback_data="how_it_works"
        )]
    ]
    # Кнопка админ-панели для админа
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(
            "👑 Админ-панель",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/admin")
        )])
    return InlineKeyboardMarkup(buttons)


def get_no_subscription_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура для пользователя без подписки"""
    buttons = [
        [InlineKeyboardButton(
            f"💳 Оформить подписку ({SUBSCRIPTION_PRICE} ₽/мес)",
            callback_data="payment_new"
        )],
        # Настройки теперь только в Mini App
        [InlineKeyboardButton("ℹ️ Справка", callback_data="help"),
         InlineKeyboardButton("👨‍💻 Поддержка", callback_data="support")]
    ]
    # Кнопка админ-панели для админа
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(
            "👑 Админ-панель",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/admin")
        )])
    return InlineKeyboardMarkup(buttons)


def get_main_menu_keyboard(questions_left: int = 10, user_id: int = 0) -> InlineKeyboardMarkup:
    """Главное меню — кнопка Mini App + поддержка"""
    buttons = [
        # Главная кнопка — открывает Mini App с прогнозами
        [InlineKeyboardButton(
            "🌟 ОТКРЫТЬ ПРОГНОЗЫ 🌟",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/webapp")
        )],
        # Настройки теперь только в Mini App
        [InlineKeyboardButton("👨‍💻 Поддержка", callback_data="support")]
    ]

    # Кнопка админ-панели для админа — открывает веб-админку
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(
            "👑 Админ-панель",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/admin")
        )])
    return InlineKeyboardMarkup(buttons)


def get_period_keyboard() -> InlineKeyboardMarkup:
    """Выбор периода прогноза"""
    buttons = [
        [InlineKeyboardButton("📅 На 2-3 дня", callback_data="forecast_3d")],
        [InlineKeyboardButton("📅 На неделю", callback_data="forecast_week")],
        [InlineKeyboardButton("📅 На месяц", callback_data="forecast_month")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_calendar_keyboard(
    year: int = None,
    month: int = None,
    selected_date: date = None
) -> InlineKeyboardMarkup:
    """Календарь для выбора даты"""
    if year is None:
        year = datetime.now().year
    if month is None:
        month = datetime.now().month

    today = date.today()
    max_date = today + timedelta(days=30)

    # Названия месяцев
    months_ru = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ]

    buttons = []

    # Заголовок с навигацией
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    header = [
        InlineKeyboardButton("◀️", callback_data=f"cal_nav_{prev_year}_{prev_month}"),
        InlineKeyboardButton(f"{months_ru[month]} {year}", callback_data="cal_ignore"),
        InlineKeyboardButton("▶️", callback_data=f"cal_nav_{next_year}_{next_month}")
    ]
    buttons.append(header)

    # Дни недели
    days_header = [
        InlineKeyboardButton(d, callback_data="cal_ignore")
        for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    ]
    buttons.append(days_header)

    # Определяем первый день месяца
    first_day = date(year, month, 1)
    start_weekday = first_day.weekday()

    # Количество дней в месяце
    if month == 12:
        days_in_month = (date(year + 1, 1, 1) - first_day).days
    else:
        days_in_month = (date(year, month + 1, 1) - first_day).days

    # Генерируем дни
    day = 1
    for week in range(6):  # Максимум 6 недель
        row = []
        for weekday in range(7):
            if (week == 0 and weekday < start_weekday) or day > days_in_month:
                row.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))
            else:
                current_date = date(year, month, day)
                if current_date < today or current_date > max_date:
                    # Недоступная дата
                    row.append(InlineKeyboardButton(
                        f"·{day}·",
                        callback_data="cal_ignore"
                    ))
                elif selected_date and current_date == selected_date:
                    # Выбранная дата
                    row.append(InlineKeyboardButton(
                        f"[{day}]",
                        callback_data=f"cal_day_{current_date.isoformat()}"
                    ))
                elif current_date == today:
                    # Сегодня
                    row.append(InlineKeyboardButton(
                        f"•{day}•",
                        callback_data=f"cal_day_{current_date.isoformat()}"
                    ))
                else:
                    row.append(InlineKeyboardButton(
                        str(day),
                        callback_data=f"cal_day_{current_date.isoformat()}"
                    ))
                day += 1
        buttons.append(row)
        if day > days_in_month:
            break

    # Кнопка назад
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])

    return InlineKeyboardMarkup(buttons)


def get_forecast_keyboard(forecast_id: int) -> InlineKeyboardMarkup:
    """Клавиатура под прогнозом"""
    buttons = [
        [
            InlineKeyboardButton(
                "💬 Задать вопрос",
                callback_data=f"ask_about_forecast:{forecast_id}"
            ),
            InlineKeyboardButton(
                "🔊 Озвучить",
                callback_data=f"voice_forecast:{forecast_id}"
            )
        ],
        [InlineKeyboardButton("🔮 Главное меню", callback_data="back_main_keep")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_question_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура в режиме вопросов"""
    buttons = [
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_answer_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура после ответа AI"""
    buttons = [
        [
            InlineKeyboardButton("💬 Ещё вопрос", callback_data="ask_question"),
            InlineKeyboardButton("🔊 Озвучить", callback_data="voice_answer")
        ],
        [InlineKeyboardButton("🔮 Главное меню", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_settings_keyboard(
    push_enabled: bool = False,
    has_active_sub: bool = True
) -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    push_btn_text = "🔕 Выкл" if push_enabled else "🔔 Вкл"
    push_callback = "settings_push_off" if push_enabled else "settings_push_on"

    buttons = [
        [InlineKeyboardButton("⏰ Изменить время прогноза", callback_data="settings_time")],
        [InlineKeyboardButton(
            f"Уведомления о транзитах: {push_btn_text}",
            callback_data=push_callback
        )]
    ]

    if has_active_sub:
        buttons.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="payment_extend")])

    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])

    return InlineKeyboardMarkup(buttons)


def get_time_selection_keyboard(current_time: str = "09:00") -> InlineKeyboardMarkup:
    """Выбор времени прогноза"""
    times = [
        ["06:00", "07:00", "08:00"],
        ["09:00", "10:00", "11:00"],
        ["12:00", "13:00", "14:00"],
        ["18:00", "20:00", "22:00"]
    ]

    buttons = []
    for row in times:
        btn_row = []
        for t in row:
            text = f"{t}✓" if t == current_time else t
            btn_row.append(InlineKeyboardButton(text, callback_data=f"set_time_{t}"))
        buttons.append(btn_row)

    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="settings")])
    return InlineKeyboardMarkup(buttons)


def get_help_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура справки"""
    buttons = [
        [InlineKeyboardButton("📚 Подробнее о методе", callback_data="help_method")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_support_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура поддержки"""
    buttons = [
        [InlineKeyboardButton("📝 Написать в поддержку", callback_data="support_new")],
        [InlineKeyboardButton("📋 Мои обращения", callback_data="support_list")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_payment_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура оплаты"""
    buttons = [
        [InlineKeyboardButton(f"💳 Оплатить {SUBSCRIPTION_PRICE} ₽", callback_data="payment_create")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_payment_pending_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    """Клавиатура ожидания оплаты"""
    buttons = [
        [InlineKeyboardButton("🔗 Перейти к оплате", url=payment_url)],
        [InlineKeyboardButton("✅ Я оплатил", callback_data="payment_check")],
        [InlineKeyboardButton("❌ Отмена", callback_data="payment_cancel")]
    ]
    return InlineKeyboardMarkup(buttons)


# ============== АДМИН-КЛАВИАТУРЫ ==============

def get_admin_main_keyboard(support_count: int = 0) -> InlineKeyboardMarkup:
    """Главное меню админки"""
    support_text = f"💬 Поддержка ({support_count})" if support_count > 0 else "💬 Поддержка"

    buttons = [
        [
            InlineKeyboardButton("👥 Пользователи", callback_data="adm_users"),
            InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")
        ],
        [
            InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"),
            InlineKeyboardButton(support_text, callback_data="adm_support")
        ],
        [InlineKeyboardButton("➕ Добавить клиента", callback_data="adm_add_user")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="adm_close")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_users_filter_keyboard(
    current_filter: str = "all",
    counts: dict = None
) -> InlineKeyboardMarkup:
    """Фильтры списка пользователей"""
    if counts is None:
        counts = {"all": 0, "active": 0, "expired": 0, "expiring": 0, "nodata": 0}

    filters = [
        ("all", f"Все ({counts.get('all', 0)})"),
        ("active", f"✅ Активные ({counts.get('active', 0)})"),
        ("expired", f"❌ Истёкшие ({counts.get('expired', 0)})"),
        ("expiring", f"⏰ Истекают ({counts.get('expiring', 0)})"),
        ("nodata", f"⚠️ Без данных ({counts.get('nodata', 0)})")
    ]

    buttons = []
    for filter_key, text in filters:
        if filter_key == current_filter:
            text = f"[{text}]"
        buttons.append([InlineKeyboardButton(text, callback_data=f"adm_users_filter_{filter_key}")])

    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="adm_main")])
    return InlineKeyboardMarkup(buttons)


def get_admin_users_list_keyboard(
    users: List,
    page: int = 0,
    per_page: int = 5,
    current_filter: str = "all"
) -> InlineKeyboardMarkup:
    """Список пользователей с пагинацией"""
    buttons = []

    start = page * per_page
    end = start + per_page
    page_users = users[start:end]

    for user in page_users:
        # Определяем статус
        if not user.natal_data_complete:
            status = "⚠️"
        elif user.has_active_subscription():
            sub = user.get_subscription()
            if sub and sub.is_expiring_soon:
                status = "⏰"
            else:
                status = "✅"
        else:
            status = "❌"

        name = user.display_name[:20]
        buttons.append([InlineKeyboardButton(
            f"{status} {name}",
            callback_data=f"adm_user_{user.telegram_id}"
        )])

    # Пагинация
    total_pages = (len(users) + per_page - 1) // per_page
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️", callback_data=f"adm_users_page_{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="adm_ignore"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("▶️", callback_data=f"adm_users_page_{page + 1}"))
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🔍 Фильтры", callback_data="adm_users_filters")])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="adm_main")])

    return InlineKeyboardMarkup(buttons)


def get_admin_user_card_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Карточка пользователя (админ)"""
    buttons = [
        [InlineKeyboardButton("✏️ Редактировать данные", callback_data=f"adm_edit_user_{user_id}")],
        [InlineKeyboardButton("💳 Управление подпиской →", callback_data=f"adm_sub_{user_id}")],
        [InlineKeyboardButton("📨 Написать пользователю", callback_data=f"adm_msg_{user_id}")],
        [InlineKeyboardButton("🔮 Отправить прогноз сейчас", callback_data=f"adm_send_forecast_{user_id}")],
        [InlineKeyboardButton("📋 История прогнозов", callback_data=f"adm_history_{user_id}")],
        [InlineKeyboardButton("🗑 Удалить пользователя", callback_data=f"adm_delete_{user_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="adm_users")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_edit_user_keyboard(user_id: int, user_data: dict) -> InlineKeyboardMarkup:
    """Редактирование данных пользователя"""
    birth_date = user_data.get("birth_date", "Не указано")
    birth_time = user_data.get("birth_time", "Не указано")
    birth_place = user_data.get("birth_place", "Не указано")
    residence = user_data.get("residence_place", "Не указано")
    name = user_data.get("first_name", "Не указано")

    buttons = [
        [InlineKeyboardButton(f"📅 Дата рождения: {birth_date}", callback_data=f"adm_edit_birth_date_{user_id}")],
        [InlineKeyboardButton(f"⏰ Время рождения: {birth_time}", callback_data=f"adm_edit_birth_time_{user_id}")],
        [InlineKeyboardButton(f"📍 Место рождения: {birth_place}", callback_data=f"adm_edit_birth_place_{user_id}")],
        [InlineKeyboardButton(f"🏠 Проживание: {residence}", callback_data=f"adm_edit_residence_{user_id}")],
        [InlineKeyboardButton(f"👤 Имя: {name}", callback_data=f"adm_edit_name_{user_id}")],
        [InlineKeyboardButton("◀️ Назад к профилю", callback_data=f"adm_user_{user_id}")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_subscription_keyboard(user_id: int, has_active: bool = False) -> InlineKeyboardMarkup:
    """Управление подпиской пользователя"""
    buttons = [
        [InlineKeyboardButton("➕ Продлить на 30 дней", callback_data=f"adm_sub_extend_{user_id}")],
        [InlineKeyboardButton("📅 Установить дату окончания", callback_data=f"adm_sub_set_date_{user_id}")],
        [InlineKeyboardButton("🎁 Активировать бесплатно", callback_data=f"adm_sub_free_{user_id}")]
    ]

    if has_active:
        buttons.append([InlineKeyboardButton("❌ Отменить подписку", callback_data=f"adm_sub_cancel_{user_id}")])

    buttons.append([InlineKeyboardButton("◀️ Назад к профилю", callback_data=f"adm_user_{user_id}")])
    return InlineKeyboardMarkup(buttons)


def get_admin_broadcast_audience_keyboard() -> InlineKeyboardMarkup:
    """Выбор аудитории для рассылки"""
    buttons = [
        [InlineKeyboardButton("👥 Все пользователи", callback_data="adm_bcast_all")],
        [InlineKeyboardButton("✅ С активной подпиской", callback_data="adm_bcast_active")],
        [InlineKeyboardButton("❌ С истёкшей подпиской", callback_data="adm_bcast_expired")],
        [InlineKeyboardButton("⏰ Подписка истекает скоро", callback_data="adm_bcast_expiring")],
        [InlineKeyboardButton("◀️ Назад", callback_data="adm_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение рассылки"""
    buttons = [
        [
            InlineKeyboardButton("✅ Отправить", callback_data="adm_bcast_send"),
            InlineKeyboardButton("✏️ Редактировать", callback_data="adm_bcast_edit")
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="adm_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_support_keyboard(tickets: List, filter_type: str = "new") -> InlineKeyboardMarkup:
    """Список тикетов поддержки"""
    buttons = []

    # Фильтры
    filters_row = [
        InlineKeyboardButton(
            f"{'[' if filter_type == 'new' else ''}🔴 Новые{']}' if filter_type == 'new' else ''}",
            callback_data="adm_support_new"
        ),
        InlineKeyboardButton(
            f"{'[' if filter_type == 'progress' else ''}🟡 В работе{']}' if filter_type == 'progress' else ''}",
            callback_data="adm_support_progress"
        ),
        InlineKeyboardButton(
            f"{'[' if filter_type == 'closed' else ''}🟢 Закрытые{']}' if filter_type == 'closed' else ''}",
            callback_data="adm_support_closed"
        )
    ]
    buttons.append(filters_row)

    # Тикеты
    for ticket in tickets[:10]:
        user_name = ticket.user.display_name[:15] if ticket.user else "Unknown"
        preview = ticket.last_message_preview[:25] if ticket.last_message_preview else ""
        buttons.append([InlineKeyboardButton(
            f"#{ticket.id} — {user_name}: {preview}",
            callback_data=f"adm_ticket_{ticket.id}"
        )])

    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="adm_main")])
    return InlineKeyboardMarkup(buttons)


def get_admin_ticket_keyboard(ticket_id: int, user_id: int) -> InlineKeyboardMarkup:
    """Карточка тикета"""
    buttons = [
        [InlineKeyboardButton("👤 Профиль пользователя", callback_data=f"adm_user_{user_id}")],
        [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"adm_ticket_close_{ticket_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="adm_support")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="adm_cancel")]])


def get_confirm_city_keyboard(city_name: str) -> InlineKeyboardMarkup:
    """Подтверждение города"""
    buttons = [
        [
            InlineKeyboardButton("✅ Да, верно", callback_data="city_confirm"),
            InlineKeyboardButton("🔄 Искать другой", callback_data="city_retry")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_add_user_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение добавления пользователя"""
    buttons = [
        [
            InlineKeyboardButton("✅ Сохранить", callback_data="adm_add_save"),
            InlineKeyboardButton("✏️ Редактировать", callback_data="adm_add_edit")
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="adm_main")]
    ]
    return InlineKeyboardMarkup(buttons)


# ============== КЛАВИАТУРЫ СОГЛАСИЙ (152-ФЗ, 38-ФЗ) ==============

def get_pd_consent_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура согласия на обработку ПД"""
    buttons = [
        [InlineKeyboardButton("✅ СОГЛАСЕН", callback_data="consent_pd_yes")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_marketing_consent_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура согласия на рассылку"""
    buttons = [
        [
            InlineKeyboardButton("✅ Подписаться", callback_data="consent_marketing_yes"),
            InlineKeyboardButton("❌ Не сейчас", callback_data="consent_marketing_no")
        ]
    ]
    return InlineKeyboardMarkup(buttons)
