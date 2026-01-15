#!/usr/bin/env python3
# coding: utf-8

"""
Модели базы данных для Астро-бота (Peewee ORM)
"""

import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Dict

from peewee import (
    SqliteDatabase, Model,
    BigIntegerField, CharField, TextField,
    DateField, TimeField, DateTimeField,
    FloatField, BooleanField, IntegerField, DecimalField,
    ForeignKeyField
)

from config import DB_PATH, SUBSCRIPTION_DAYS

logger = logging.getLogger(__name__)

# Инициализация БД
db = SqliteDatabase(DB_PATH, pragmas={
    'journal_mode': 'wal',
    'cache_size': -1 * 64000,
    'foreign_keys': 1,
    'ignore_check_constraints': 0,
    'synchronous': 1,  # NORMAL — баланс между производительностью и безопасностью
    'busy_timeout': 5000  # 5 секунд ожидания при блокировке БД
})


class BaseModel(Model):
    """Базовая модель"""
    class Meta:
        database = db


class User(BaseModel):
    """Пользователь бота"""

    telegram_id = BigIntegerField(primary_key=True)
    username = CharField(null=True)
    first_name = CharField(default="")

    # Натальные данные (заполняет админ)
    birth_date = DateField(null=True)
    birth_time = TimeField(null=True)
    birth_place = CharField(null=True)
    birth_lat = FloatField(null=True)
    birth_lon = FloatField(null=True)
    birth_tz = CharField(null=True)

    # Место проживания
    residence_place = CharField(null=True)
    residence_lat = FloatField(null=True)
    residence_lon = FloatField(null=True)
    residence_tz = CharField(default="Europe/Moscow")

    # Настройки
    forecast_time = CharField(default="09:00")
    push_forecast = BooleanField(default=True)  # Утренний прогноз вкл/выкл
    push_transits = BooleanField(default=False)  # Важные транзиты вкл/выкл

    # Лимиты вопросов
    questions_today = IntegerField(default=0)
    questions_reset_date = DateField(null=True)

    # Статусы
    is_active = BooleanField(default=True)
    is_admin = BooleanField(default=False)
    natal_data_complete = BooleanField(default=False)

    # Время
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'users'

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        """Отображаемое имя"""
        return self.first_name or f"User {self.telegram_id}"

    @property
    def birth_datetime_str(self) -> str:
        """Дата и время рождения строкой"""
        if not self.birth_date:
            return "Не указано"
        date_str = self.birth_date.strftime("%d.%m.%Y")
        if self.birth_time:
            time_str = self.birth_time.strftime("%H:%M:%S") if hasattr(self.birth_time, 'strftime') else str(self.birth_time)[:8]
            return f"{date_str}, {time_str}"
        return date_str

    def has_natal_data(self) -> bool:
        """Проверка наличия натальных данных"""
        return all([
            self.birth_date,
            self.birth_time,
            self.birth_place,
            self.birth_lat,
            self.birth_lon
        ])

    def get_subscription(self) -> Optional['Subscription']:
        """Получить текущую подписку"""
        return Subscription.select().where(
            Subscription.user == self,
            Subscription.status.in_(['active', 'expiring_soon'])
        ).order_by(Subscription.expires_at.desc()).first()

    def has_active_subscription(self) -> bool:
        """Есть ли активная подписка"""
        sub = self.get_subscription()
        if not sub:
            return False
        return sub.status in ['active', 'expiring_soon'] and sub.expires_at > datetime.now()

    def get_questions_remaining(self) -> int:
        """Сколько вопросов осталось сегодня"""
        from config import QUESTIONS_PER_DAY

        # Сброс счётчика если новый день
        today = date.today()
        if self.questions_reset_date != today:
            self.questions_today = 0
            self.questions_reset_date = today
            self.save()

        return max(0, QUESTIONS_PER_DAY - self.questions_today)

    def use_question(self) -> bool:
        """Использовать один вопрос. Возвращает True если успешно"""
        if self.get_questions_remaining() <= 0:
            return False

        self.questions_today += 1
        self.save()
        return True


class Subscription(BaseModel):
    """Подписка пользователя"""

    user = ForeignKeyField(User, backref='subscriptions', on_delete='CASCADE')

    status = CharField(default="pending")  # pending, active, expiring_soon, expired
    started_at = DateTimeField(null=True)
    expires_at = DateTimeField(null=True)

    # Платёж
    payment_id = CharField(null=True)
    amount = DecimalField(decimal_places=2, null=True)

    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'subscriptions'

    @property
    def days_left(self) -> int:
        """Дней до окончания"""
        if not self.expires_at:
            return 0
        delta = self.expires_at - datetime.now()
        return max(0, delta.days)

    @property
    def is_expiring_soon(self) -> bool:
        """Истекает в ближайшие 3 дня"""
        return 0 < self.days_left <= 3

    def activate(self, days: int = None):
        """Активировать подписку"""
        days = days or SUBSCRIPTION_DAYS
        now = datetime.now()

        # Если есть активная подписка — продлеваем от её конца
        if self.expires_at and self.expires_at > now:
            self.expires_at = self.expires_at + timedelta(days=days)
        else:
            self.started_at = now
            self.expires_at = now + timedelta(days=days)

        self.status = "active"
        self.save()

    def cancel(self):
        """Отменить подписку"""
        self.status = "expired"
        self.save()

    @classmethod
    def create_for_user(cls, user: User, amount: Decimal = None, payment_id: str = None) -> 'Subscription':
        """Создать новую подписку для пользователя"""
        return cls.create(
            user=user,
            status="pending",
            amount=amount,
            payment_id=payment_id
        )


class Forecast(BaseModel):
    """История прогнозов"""

    user = ForeignKeyField(User, backref='forecasts', on_delete='CASCADE')

    forecast_type = CharField()  # daily, period_3d, weekly, monthly, date
    target_date = DateField()
    period_end = DateField(null=True)

    transits_data = TextField(null=True)  # JSON
    forecast_text = TextField()

    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'forecasts'


class Conversation(BaseModel):
    """Контекст диалога с AI"""

    user = ForeignKeyField(User, backref='conversations', on_delete='CASCADE')
    forecast = ForeignKeyField(Forecast, null=True, on_delete='SET NULL')

    messages = TextField(default="[]")  # JSON массив

    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'conversations'

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    def get_messages(self) -> List[Dict]:
        """Получить сообщения как список словарей"""
        import json
        try:
            return json.loads(self.messages)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_messages(self, messages: List[Dict]):
        """Установить сообщения из списка словарей"""
        import json
        self.messages = json.dumps(messages, ensure_ascii=False)


class CalendarCache(BaseModel):
    """Кэш календаря (рассчитанные данные на месяц)"""

    user = ForeignKeyField(User, backref='calendar_caches', on_delete='CASCADE')

    year = IntegerField()
    month = IntegerField()
    days_data = TextField()  # JSON с данными дней: [{"date": "01.01.2026", "mood": "good"}, ...]

    created_at = DateTimeField(default=datetime.now)
    expires_at = DateTimeField()  # TTL — через месяц удаляется

    class Meta:
        table_name = 'calendar_cache'
        indexes = (
            (('user', 'year', 'month'), True),  # Уникальный индекс
        )

    def get_days(self) -> List[Dict]:
        """Получить данные дней как список"""
        import json
        try:
            return json.loads(self.days_data)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_days(self, days: List[Dict]):
        """Сохранить данные дней"""
        import json
        self.days_data = json.dumps(days, ensure_ascii=False)

    def is_valid(self) -> bool:
        """Проверить, не истёк ли кэш"""
        return self.expires_at > datetime.now()

    @classmethod
    def get_cached(cls, user_id: int, year: int, month: int) -> Optional['CalendarCache']:
        """Получить кэш календаря если он актуален"""
        cache = cls.select().where(
            cls.user == user_id,
            cls.year == year,
            cls.month == month
        ).first()
        if cache and cache.is_valid():
            return cache
        return None

    @classmethod
    def save_cache(cls, user_id: int, year: int, month: int, days: List[Dict], ttl_days: int = 30) -> 'CalendarCache':
        """Сохранить или обновить кэш календаря"""
        import json
        expires = datetime.now() + timedelta(days=ttl_days)

        cache, created = cls.get_or_create(
            user_id=user_id,
            year=year,
            month=month,
            defaults={
                'days_data': json.dumps(days, ensure_ascii=False),
                'expires_at': expires
            }
        )

        if not created:
            cache.days_data = json.dumps(days, ensure_ascii=False)
            cache.expires_at = expires
            cache.save()

        return cache

    @classmethod
    def cleanup_expired(cls):
        """Удалить устаревшие записи кэша"""
        deleted = cls.delete().where(cls.expires_at < datetime.now()).execute()
        if deleted:
            logger.info(f"Удалено {deleted} устаревших записей кэша календаря")
        return deleted

    @classmethod
    def invalidate_for_user(cls, user_id: int) -> int:
        """
        Инвалидировать весь кэш календаря для пользователя.
        Вызывается при изменении натальных данных или места проживания.

        Args:
            user_id: ID пользователя Telegram

        Returns:
            Количество удалённых записей кэша
        """
        deleted = cls.delete().where(cls.user == user_id).execute()
        if deleted:
            logger.info(f"Инвалидирован кэш календаря для user {user_id}: удалено {deleted} записей")
        return deleted


class SupportTicket(BaseModel):
    """Обращение в поддержку"""

    user = ForeignKeyField(User, backref='tickets', on_delete='CASCADE')

    status = CharField(default="open")  # open, answered, closed

    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'support_tickets'

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    @property
    def last_message_preview(self) -> str:
        """Превью последнего сообщения"""
        msg = self.messages.order_by(SupportMessage.created_at.desc()).first()
        if msg:
            return msg.message_text[:50] + "..." if len(msg.message_text) > 50 else msg.message_text
        return ""


class SupportMessage(BaseModel):
    """Сообщение в тикете поддержки"""

    ticket = ForeignKeyField(SupportTicket, backref='messages', on_delete='CASCADE')

    sender_type = CharField()  # user, admin
    sender_id = BigIntegerField()
    message_text = TextField()
    message_type = CharField(default="text")  # text, voice, photo

    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'support_messages'


# ============== ИНИЦИАЛИЗАЦИЯ ==============

def init_db():
    """Инициализация базы данных"""
    db.connect(reuse_if_open=True)
    db.create_tables([
        User,
        Subscription,
        Forecast,
        Conversation,
        CalendarCache,
        SupportTicket,
        SupportMessage
    ], safe=True)
    logger.info("База данных инициализирована")


def get_or_create_user(
    telegram_id: int,
    username: str = None,
    first_name: str = None
) -> tuple[User, bool]:
    """Получить или создать пользователя"""
    user, created = User.get_or_create(
        telegram_id=telegram_id,
        defaults={
            'username': username,
            'first_name': first_name or ""
        }
    )

    # Обновляем данные если пользователь уже существует
    if not created:
        updated = False
        if username and user.username != username:
            user.username = username
            updated = True
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            updated = True
        if updated:
            user.save()

    return user, created


def get_stats() -> dict:
    """Получить статистику для админ-панели"""
    from datetime import timedelta

    today = date.today()
    three_days = datetime.now() + timedelta(days=3)

    total_users = User.select().count()
    with_data = User.select().where(User.natal_data_complete == True).count()
    without_data = total_users - with_data

    # Подписки
    active_subs = Subscription.select().where(
        Subscription.status.in_(['active', 'expiring_soon']),
        Subscription.expires_at > datetime.now()
    ).count()

    expiring_soon = Subscription.select().where(
        Subscription.status.in_(['active', 'expiring_soon']),
        Subscription.expires_at <= three_days,
        Subscription.expires_at > datetime.now()
    ).count()

    expired = Subscription.select().where(
        Subscription.status == 'expired'
    ).count()

    # Финансы — сумма всех оплат
    from peewee import fn
    total_revenue = Subscription.select(
        fn.COALESCE(fn.SUM(Subscription.amount), 0)
    ).where(
        Subscription.amount.is_null(False)
    ).scalar() or 0

    return {
        'total_users': total_users,
        'with_data': with_data,
        'without_data': without_data,
        'active_subs': active_subs,
        'expiring_soon': expiring_soon,
        'expired': expired,
        'total_revenue': total_revenue
    }
