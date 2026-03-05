# services/logging_service.py

import re
from datetime import datetime
from typing import Any, Dict, Optional

from database.connection import get_connection


# -----------------------------
# Sensitive data redaction
# -----------------------------
_PAN_CANDIDATE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")  # 13–19 digits with optional spaces/dashes
_CVV_CANDIDATE = re.compile(r"\b(cvv|ccv|cvc)\b\s*[:=]?\s*\d{3,4}\b", re.IGNORECASE)
_EXP_CANDIDATE = re.compile(r"\b(?:exp|expiry|expiration)\b\s*[:=]?\s*\d{1,2}\s*/\s*\d{2,4}\b", re.IGNORECASE)


def _mask_pan(match: re.Match) -> str:
    raw = match.group(0)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 12:
        return raw
    # keep last 4, mask the rest
    masked_digits = "*" * (len(digits) - 4) + digits[-4:]
    return masked_digits


def sanitize_message(message: str) -> str:
    """
    Redacts common payment-sensitive strings (PAN/CVV/expiration) from logs.
    """
    if not message:
        return message

    cleaned = message

    # Mask PAN-like sequences
    cleaned = _PAN_CANDIDATE.sub(_mask_pan, cleaned)

    # Remove CVV/CCV/CVC patterns
    cleaned = _CVV_CANDIDATE.sub("CVV:***", cleaned)

    # Remove exp-like patterns
    cleaned = _EXP_CANDIDATE.sub("EXP:**/**", cleaned)

    return cleaned


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

    Expected (recommended) table columns:
      - id (auto)
      - order_id (varchar, nullable)
      - event_type (varchar)
      - level (varchar)
      - message (text)
      - metadata (json/text, optional)
      - created_at (datetime)

    If your table does NOT include metadata or level, this function will
    fall back automatically to a simpler INSERT.
    """
    safe_message = sanitize_message(message)
    safe_event_type = (event_type or "EVENT").strip()[:100]
    safe_level = (level or "INFO").strip()[:20]
    created_at = datetime.utcnow()

    # Convert metadata to a compact string if provided
    meta_str = None
    if metadata:
        # keep it lightweight; avoid logging sensitive info in metadata too
        meta_str = sanitize_message(str(metadata))[:2000]

    conn = None
    cur = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        # Try insert with metadata + level first (most complete)
        if meta_str is not None:
            cur.execute(
                """
                INSERT INTO logs (order_id, event_type, level, message, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (order_id, safe_event_type, safe_level, safe_message, meta_str, created_at),
            )
        else:
            cur.execute(
                """
                INSERT INTO logs (order_id, event_type, level, message, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, safe_event_type, safe_level, safe_message, created_at),
            )

        conn.commit()

    except Exception:
        # Fallback: try a simpler insert (in case your table doesn't have level/metadata)
        try:
            if conn is None:
                conn = get_connection()
            if cur is None:
                cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO logs (order_id, event_type, message, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (order_id, safe_event_type, safe_message, created_at),
            )
            conn.commit()
        except Exception:
            # Final fallback: console
            print(f"[{created_at.isoformat()}] {safe_level} {safe_event_type} order={order_id} {safe_message}")

    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


# Convenience aliases (optional)
def info(order_id: Optional[str], event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    log_event(order_id=order_id, event_type=event_type, message=message, level="INFO", metadata=metadata)


def error(order_id: Optional[str], event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    log_event(order_id=order_id, event_type=event_type, message=message, level="ERROR", metadata=metadata)