#!/usr/bin/env python3
# coding: utf-8

"""
Миграция: Добавление поля paid_via_bot в таблицу subscriptions
"""

import sys
import os

# Добавляем путь к src для импорта моделей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from database.models import db, Subscription
from playhouse.migrate import migrate, SqliteMigrator
from peewee import BooleanField

def add_paid_via_bot_field():
    """Добавить поле paid_via_bot в subscriptions"""

    print("🔄 Начинаем миграцию: добавление поля paid_via_bot...")
    print()

    try:
        migrator = SqliteMigrator(db)

        # Добавляем поле paid_via_bot со значением по умолчанию True
        paid_via_bot_field = BooleanField(default=True)

        migrate(
            migrator.add_column('subscriptions', 'paid_via_bot', paid_via_bot_field)
        )

        print("✅ Поле paid_via_bot успешно добавлено в таблицу subscriptions")
        print()

        # Проверяем: обновляем все существующие записи
        count = Subscription.update(paid_via_bot=True).execute()
        print(f"📊 Обновлено записей: {count}")
        print()
        print("=" * 60)
        print("✅ Миграция завершена успешно!")
        print("=" * 60)

    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        add_paid_via_bot_field()
    except KeyboardInterrupt:
        print("\n\n⚠️  Миграция прервана пользователем")
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
