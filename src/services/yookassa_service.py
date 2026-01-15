#!/usr/bin/env python3
# coding: utf-8

"""
Сервис интеграции с YooKassa для приёма платежей
"""

import logging
import uuid
import time
from typing import Optional, Dict
from decimal import Decimal

# Настройки retry
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1  # секунды

from config import (
    YOOKASSA_SHOP_ID,
    YOOKASSA_SECRET_KEY,
    SUBSCRIPTION_PRICE,
    SUBSCRIPTION_DAYS,
    BOT_RETURN_URL
)

logger = logging.getLogger(__name__)

# Инициализация YooKassa SDK
_yookassa_configured = False

try:
    from yookassa import Configuration, Payment

    if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
        Configuration.account_id = YOOKASSA_SHOP_ID
        Configuration.secret_key = YOOKASSA_SECRET_KEY
        _yookassa_configured = True
        logger.info("YooKassa SDK сконфигурирован")
    else:
        logger.warning("YooKassa: SHOP_ID или SECRET_KEY не заданы в .env")

except ImportError:
    logger.warning("YooKassa SDK не установлен. Выполните: pip install yookassa")
    Payment = None


def is_configured() -> bool:
    """Проверка настройки YooKassa"""
    return _yookassa_configured


def create_payment(
    user_id: int,
    amount: int = None,
    description: str = None,
    return_url: str = None
) -> Optional[Dict]:
    """
    Создание платежа в YooKassa

    Args:
        user_id: Telegram ID пользователя
        amount: Сумма в рублях (по умолчанию SUBSCRIPTION_PRICE)
        description: Описание платежа
        return_url: URL возврата после оплаты (опционально)

    Returns:
        dict с payment_id и confirmation_url, или None при ошибке
    """
    if not _yookassa_configured:
        logger.error("YooKassa не сконфигурирован")
        return None

    try:
        amount = amount or SUBSCRIPTION_PRICE
        description = description or f"Подписка Астро-бот на {SUBSCRIPTION_DAYS} дней"

        # Уникальный ключ идемпотентности
        idempotence_key = str(uuid.uuid4())

        payment_data = {
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url or BOT_RETURN_URL
            },
            "capture": True,
            "description": description,
            "metadata": {
                "user_id": str(user_id),
                "type": "subscription"
            }
        }

        # Retry logic для устойчивости к временным ошибкам
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                payment = Payment.create(payment_data, idempotence_key)

                logger.info(f"Создан платёж {payment.id} для пользователя {user_id}")

                return {
                    "payment_id": payment.id,
                    "confirmation_url": payment.confirmation.confirmation_url,
                    "status": payment.status,
                    "amount": amount
                }

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # Повторяем при сетевых ошибках или временных проблемах API
                if 'timeout' in error_str or 'connection' in error_str or '503' in error_str or '502' in error_str:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    logger.warning(f"YooKassa ошибка (попытка {attempt + 1}/{MAX_RETRIES}), повтор через {delay}с: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"Ошибка создания платежа: {e}")
                    return None

        logger.error(f"Ошибка создания платежа после {MAX_RETRIES} попыток: {last_error}")
        return None

    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        return None


def check_payment_status(payment_id: str) -> Optional[Dict]:
    """
    Проверка статуса платежа

    Args:
        payment_id: ID платежа в YooKassa

    Returns:
        dict со статусом и деталями, или None при ошибке
    """
    if not _yookassa_configured:
        logger.error("YooKassa не сконфигурирован")
        return None

    # Retry logic
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            payment = Payment.find_one(payment_id)

            result = {
                "payment_id": payment.id,
                "status": payment.status,  # pending, waiting_for_capture, succeeded, canceled
                "paid": payment.paid,
                "amount": float(payment.amount.value) if payment.amount else 0,
                "currency": payment.amount.currency if payment.amount else "RUB"
            }

            # Извлекаем user_id из метаданных
            if payment.metadata:
                result["user_id"] = payment.metadata.get("user_id")

            logger.info(f"Статус платежа {payment_id}: {payment.status}")

            return result

        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            if 'timeout' in error_str or 'connection' in error_str or '503' in error_str or '502' in error_str:
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(f"YooKassa ошибка проверки статуса (попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(delay)
            else:
                logger.error(f"Ошибка проверки платежа {payment_id}: {e}")
                return None

    logger.error(f"Ошибка проверки платежа {payment_id} после {MAX_RETRIES} попыток: {last_error}")
    return None


def cancel_payment(payment_id: str) -> bool:
    """
    Отмена платежа (если ещё не оплачен)

    Args:
        payment_id: ID платежа

    Returns:
        True если успешно отменён
    """
    if not _yookassa_configured:
        return False

    try:
        payment = Payment.find_one(payment_id)

        if payment.status == "pending":
            Payment.cancel(payment_id)
            logger.info(f"Платёж {payment_id} отменён")
            return True
        else:
            logger.warning(f"Платёж {payment_id} не может быть отменён (статус: {payment.status})")
            return False

    except Exception as e:
        logger.error(f"Ошибка отмены платежа {payment_id}: {e}")
        return False


def get_payment_status_text(status: str) -> str:
    """Текстовое описание статуса платежа"""
    statuses = {
        "pending": "Ожидает оплаты",
        "waiting_for_capture": "Ожидает подтверждения",
        "succeeded": "Оплачен",
        "canceled": "Отменён"
    }
    return statuses.get(status, status)
