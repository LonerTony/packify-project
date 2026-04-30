# services/logging_service.py

import json
import re
from typing import Any, Dict, Optional

from database.connection import get_connection


# -----------------------------
# Sensitive data redaction
# -----------------------------
_PAN_CANDIDATE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_CVV_CANDIDATE = re.compile(r"\b(cvv|ccv|cvc)\b\s*[:=]?\s*\d{3,4}\b", re.IGNORECASE)
_EXP_CANDIDATE = re.compile(r"\b(?:exp|expiry|expiration)\b\s*[:=]?\s*\d{1,2}\s*/\s*\d{2,4}\b", re.IGNORECASE)


def _mask_pan(match: re.Match) -> str:
    raw = match.group(0)
    digits = "".join(ch for ch in raw if ch.isdigit())

    if len(digits) < 12:
        return raw

    return "*" * (len(digits) - 4) + digits[-4:]


def sanitize_message(message: str) -> str:
    """
    Redacts common payment-sensitive strings (PAN/CVV/expiration) from logs.
    """
    if not message:
        return message

    cleaned = message
    cleaned = _PAN_CANDIDATE.sub(_mask_pan, cleaned)
    cleaned = _CVV_CANDIDATE.sub("CVV:***", cleaned)
    cleaned = _EXP_CANDIDATE.sub("EXP:**/**", cleaned)

    return cleaned


def _serialize_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    if not metadata:
        return None

    try:
        serialized = json.dumps(metadata, default=str)
    except Exception:
        serialized = str(metadata)

    return sanitize_message(serialized)[:2000]


# -----------------------------
# Main logger
# -----------------------------
def log_event(
    *,
    order_id: Optional[str],
    event_type: str,
    message: str,
    level: str = "INFO",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Inserts a log record into the MySQL logs table.
    Uses DB default timestamp from schema.
    """
    safe_message = sanitize_message(message)
    safe_event_type = (event_type or "EVENT").strip()[:100]
    safe_level = (level or "INFO").strip().upper()[:20]
    meta_str = _serialize_metadata(metadata)

    conn = None
    cur = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        if meta_str is not None:
            cur.execute(
                """
                INSERT INTO logs (order_id, event_type, level, message, metadata)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, safe_event_type, safe_level, safe_message, meta_str),
            )
        else:
            cur.execute(
                """
                INSERT INTO logs (order_id, event_type, level, message)
                VALUES (%s, %s, %s, %s)
                """,
                (order_id, safe_event_type, safe_level, safe_message),
            )

        conn.commit()

    except Exception:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass

        conn = None
        cur = None

        try:
            conn = get_connection()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO logs (order_id, event_type, message)
                VALUES (%s, %s, %s)
                """,
                (order_id, safe_event_type, safe_message),
            )
            conn.commit()

        except Exception:
            print(f"{safe_level} {safe_event_type} order={order_id} {safe_message}")

    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


def info(order_id: Optional[str], event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    log_event(
        order_id=order_id,
        event_type=event_type,
        message=message,
        level="INFO",
        metadata=metadata,
    )


def error(order_id: Optional[str], event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    log_event(
        order_id=order_id,
        event_type=event_type,
        message=message,
        level="ERROR",
        metadata=metadata,
    )