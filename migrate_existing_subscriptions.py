#!/usr/bin/env python3
# coding: utf-8

"""
Миграция существующих подписок
Проставляет payment_id = "migrated" для всех активных подписок без payment_id
"""

import sys
import os

# Добавляем путь к src для импорта моделей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from database.models import Subscription, db

def migrate_subscriptions():
    """Обновить существующие подписки"""

    print("🔄 Начинаем миграцию существующих подписок...")
    print()

    # Находим активные подписки без payment_id
    query = Subscription.select().where(
        (Subscription.status == "active") &
        (Subscription.payment_id.is_null())
    )

    count = query.count()

    if count == 0:
        print("✅ Нет подписок для миграции (все уже имеют payment_id)")
        return

    print(f"📊 Найдено подписок для обновления: {count}")
    print()

    # Подтверждение
    response = input(f"❓ Обновить {count} подписок? (yes/no): ")
    if response.lower() not in ['yes', 'y', 'да']:
        print("❌ Миграция отменена")
        return

    # Обновляем
    updated = 0
    errors = 0

    for sub in query:
        try:
            sub.payment_id = "migrated"
            sub.save()
            updated += 1

            user = sub.user
            print(f"✅ User {user.telegram_id} (@{user.username or 'без username'}) - подписка до {sub.expires_at.strftime('%d.%m.%Y')}")

        except Exception as e:
            errors += 1
            print(f"❌ Ошибка обновления подписки ID {sub.id}: {e}")

    print()
    print("=" * 60)
    print(f"✅ Миграция завершена!")
    print(f"   Обновлено: {updated}")
    if errors > 0:
        print(f"   Ошибок: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        migrate_subscriptions()
    except KeyboardInterrupt:
        print("\n\n⚠️  Миграция прервана пользователем")
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
