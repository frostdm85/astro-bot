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

    # Данные о браке (заполняет пользователь)
    marriage_date = DateField(null=True)
    marriage_city = CharField(null=True)

    # Флаг сбора данных от пользователя
    user_data_submitted = BooleanField(default=False)
    user_data_submitted_at = DateTimeField(null=True)

    # Согласие на обработку персональных данных
    consent_given = BooleanField(default=False)
    consent_given_at = DateTimeField(null=True)

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
        """Есть ли активная подписка (оплачена и срок не истёк)"""
        sub = self.get_subscription()
        if not sub:
            return False
        # Проверяем: статус активен, срок не истёк, И есть payment_id (оплачена)
        return (
            sub.status in ['active', 'expiring_soon'] and
            sub.expires_at > datetime.now() and
            sub.payment_id is not None
        )

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
    plan = CharField(null=True)  # 1_month, 3_months, 6_months, 1_year

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

        # Если payment_id не был задан - значит это назначение админом
        if not self.payment_id:
            self.payment_id = "admin_granted"

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


class MoonPhase(BaseModel):
    """Предрасчитанные лунные фазы (new_moon, full_moon)"""

    phase_type = CharField()  # new_moon, full_moon
    phase_date = DateField()
    phase_time = CharField()  # HH:MM
    phase_datetime = DateTimeField()  # Полный datetime для сортировки

    class Meta:
        table_name = 'moon_phases'
        indexes = (
            (('phase_date',), False),
        )


class Eclipse(BaseModel):
    """Предрасчитанные затмения"""

    eclipse_type = CharField()  # solar, lunar
    eclipse_date = DateField()
    eclipse_time = CharField()  # HH:MM
    eclipse_datetime = DateTimeField()
    description = TextField(null=True)

    class Meta:
        table_name = 'eclipses'
        indexes = (
            (('eclipse_date',), False),
        )


# ============== МИГРАЦИИ ==============

def run_migrations():
    """Выполнить миграции базы данных"""
    from playhouse.migrate import SqliteMigrator, migrate as run_migrate

    migrator = SqliteMigrator(db)

    # Проверяем существующие столбцы в таблице users
    cursor = db.execute_sql("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    migrations = []

    # Миграция: добавление полей сбора данных от пользователя
    if 'marriage_date' not in columns:
        logger.info("Добавление поля marriage_date в таблицу users")
        migrations.append(migrator.add_column('users', 'marriage_date', DateField(null=True)))

    if 'marriage_city' not in columns:
        logger.info("Добавление поля marriage_city в таблицу users")
        migrations.append(migrator.add_column('users', 'marriage_city', CharField(null=True)))

    if 'user_data_submitted' not in columns:
        logger.info("Добавление поля user_data_submitted в таблицу users")
        migrations.append(migrator.add_column('users', 'user_data_submitted', BooleanField(default=False)))

    if 'user_data_submitted_at' not in columns:
        logger.info("Добавление поля user_data_submitted_at в таблицу users")
        migrations.append(migrator.add_column('users', 'user_data_submitted_at', DateTimeField(null=True)))

    # Миграция: добавление полей согласия на обработку ПД
    if 'consent_given' not in columns:
        logger.info("Добавление поля consent_given в таблицу users")
        migrations.append(migrator.add_column('users', 'consent_given', BooleanField(default=False)))

    if 'consent_given_at' not in columns:
        logger.info("Добавление поля consent_given_at в таблицу users")
        migrations.append(migrator.add_column('users', 'consent_given_at', DateTimeField(null=True)))

    # Выполнить все миграции
    if migrations:
        run_migrate(*migrations)
        logger.info(f"Выполнено миграций: {len(migrations)}")
    else:
        logger.info("Миграции не требуются, все поля существуют")


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
        SupportMessage,
        MoonPhase,
        Eclipse
    ], safe=True)
    logger.info("База данных инициализирована")

    # Запускаем миграции
    run_migrations()

    # Предрасчитываем лунные фазы если их нет
    precalculate_moon_phases_if_needed()


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


def precalculate_moon_phases_if_needed():
    """
    Предрасчёт лунных фаз на год вперёд.
    Вызывается при инициализации БД.
    Лунные фазы одинаковы для всех пользователей.
    """
    from datetime import timedelta

    # Проверяем есть ли фазы на будущее (на 30 дней вперёд)
    today = date.today()
    future_date = today + timedelta(days=30)

    existing_count = MoonPhase.select().where(
        MoonPhase.phase_date >= today,
        MoonPhase.phase_date <= future_date
    ).count()

    # Если есть хотя бы 1 фаза в будущем - пропускаем расчёт
    if existing_count > 0:
        logger.info(f"Moon phases already calculated: {existing_count} phases found")
        return

    logger.info("Precalculating moon phases for next 365 days...")

    from services.astro_engine import find_exact_new_moon, find_exact_full_moon

    # Рассчитываем с начала текущего месяца на год вперёд
    start_dt = datetime.combine(date(today.year, today.month, 1), datetime.min.time())
    phases_to_create = []
    end_date = today + timedelta(days=365)

    # Начинаем с новолуния
    current_dt = start_dt
    for i in range(26):  # ~26 фаз в году (чередование new/full каждые ~14 дней)
        if i % 2 == 0:
            # Чётная итерация - новолуние
            phase_dt = find_exact_new_moon(current_dt)
            phase_type = 'new_moon'
        else:
            # Нечётная итерация - полнолуние
            phase_dt = find_exact_full_moon(current_dt)
            phase_type = 'full_moon'

        if phase_dt.date() > end_date:
            break

        phases_to_create.append({
            'phase_type': phase_type,
            'phase_date': phase_dt.date(),
            'phase_time': phase_dt.strftime("%H:%M"),
            'phase_datetime': phase_dt
        })

        # Следующая фаза через 14 дней
        current_dt = phase_dt + timedelta(days=14)

    # Удаляем дубликаты и сортируем
    seen = set()
    unique_phases = []
    for phase in sorted(phases_to_create, key=lambda x: x['phase_datetime']):
        key = (phase['phase_type'], phase['phase_date'])
        if key not in seen:
            seen.add(key)
            unique_phases.append(phase)

    # Массовая вставка
    if unique_phases:
        MoonPhase.insert_many(unique_phases).execute()
        logger.info(f"Precalculated {len(unique_phases)} moon phases")
    else:
        logger.warning("No moon phases to precalculate")
