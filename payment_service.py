# services/payment_service.py

import os
from typing import Any, Dict, Optional, Tuple

import requests


# ----------------------------
# Config (env-based)
# ----------------------------
TOKEN_URL = os.getenv("PAYMENT_TOKEN_URL", "https://capstoneproject.proxy.beeceptor.com/oauth/token")
AUTHORIZE_URL = os.getenv("PAYMENT_AUTHORIZE_URL", "https://capstoneproject.proxy.beeceptor.com/authorize")

MERCHANT_ID = os.getenv("PAYMENT_MERCHANT_ID", "ksuCapstone")
SECRET_KEY = os.getenv("PAYMENT_SECRET_KEY", "P@ymentP@ss!")

# Timeouts: (connect_timeout, read_timeout)
HTTP_TIMEOUT: Tuple[int, int] = (5, 15)


class PaymentServiceError(Exception):
    """Raised when the mock payment provider request fails (network/format/etc.)."""


def _safe_json(resp: requests.Response) -> Optional[Dict[str, Any]]:
    """
    Attempt to parse JSON safely. Returns None if invalid JSON.
    """
    try:
        return resp.json()
    except Exception:
        return None


def _extract_token(resp: requests.Response) -> str:
    """
    Token API expected response: "Authorization token string" (per TRD),
    but Beeceptor may return JSON or raw text depending on the mock setup.
    We'll support both.
    """
    data = _safe_json(resp)
    if isinstance(data, dict):
        # common token field names
        for key in ("access_token", "token", "authorizationToken", "authToken"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    # fallback to plain text
    text = (resp.text or "").strip().strip('"')
    if text:
        return text

    raise PaymentServiceError("Token API returned an empty token.")


def get_oauth_token() -> str:
    """
    Calls the Token API to obtain the token required for Authorization header
    in the next API call.

    Spec:
    POST https://capstoneproject.proxy.beeceptor.com/oauth/token
    Headers: Content-Type: application/json
    Body: { "merchantId": "...", "secretKey": "..." }
    """
    headers = {"Content-Type": "application/json"}
    payload = {"merchantId": MERCHANT_ID, "secretKey": SECRET_KEY}

    try:
        resp = requests.post(TOKEN_URL, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise PaymentServiceError(f"Token API request failed: {e}") from e

    if resp.status_code >= 400:
        # Do NOT include secrets in error text
        raise PaymentServiceError(f"Token API returned HTTP {resp.status_code}")

    return _extract_token(resp)


def authorize_payment(
    *,
    token: str,
    order_id: str,
    card_number: str,
    card_month: str,
    card_year: str,
    ccv: str,
    requested_amount: float,
) -> Dict[str, Any]:
    """
    Calls Authorization API.

    Spec:
    POST https://capstoneproject.proxy.beeceptor.com/authorize
    Headers:
      Content-Type: application/json
      Authorization: {{AuthorizationTokenFromTokenAPI}}
    Body:
    {
      "OrderId": "ORD123456",
      "CardDetails": {
        "CardNumber": "1111-1111-1111-1111",
        "CardMonth": "08",
        "CardYear": "2028",
        "CCV": "111"
      },
      "RequestedAmount": 50.0
    }

    Returns a normalized dict, regardless of provider response format:
    {
      "http_status": 200,
      "status": "Approved" | "Failed" | "Error",
      "authorizationToken": "...",
      "authorizedAmount": 50.0,
      "authExpiration": "...",
      "message": "..."
    }
    """
    if not token or not token.strip():
        raise PaymentServiceError("Missing OAuth token for Authorization request.")

    headers = {
        "Content-Type": "application/json",
        # Spec says token goes directly in Authorization header (no "Bearer " mentioned)
        "Authorization": token.strip(),
    }

    body = {
        "OrderId": order_id,
        "CardDetails": {
            "CardNumber": card_number,
            "CardMonth": card_month,
            "CardYear": card_year,
            "CCV": ccv,
        },
        "RequestedAmount": float(requested_amount),
    }

    try:
        resp = requests.post(AUTHORIZE_URL, json=body, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        # Treat as service unavailable / system error
        return {
            "http_status": 503,
            "status": "Error",
            "authorizationToken": "",
            "authorizedAmount": 0.0,
            "authExpiration": "",
            "message": f"Authorization request failed: {e}",
        }

    # If provider returns HTTP 500 (~6% scenario), surface as "Error"
    if resp.status_code >= 500:
        return {
            "http_status": resp.status_code,
            "status": "Error",
            "authorizationToken": "",
            "authorizedAmount": 0.0,
            "authExpiration": "",
            "message": "Payment service temporarily unavailable. Please try again later.",
        }

    data = _safe_json(resp)

    # Normalize unknown formats
    normalized: Dict[str, Any] = {
        "http_status": resp.status_code,
        "status": "Failed",
        "authorizationToken": "",
        "authorizedAmount": float(requested_amount),
        "authExpiration": "",
        "message": "",
        "raw": data if data is not None else (resp.text or "").strip(),
    }

    # If JSON dict, try to map fields
    if isinstance(data, dict):
        # status can be returned in many ways; try multiple keys
        status_val = (
            data.get("status")
            or data.get("result")
            or data.get("responseStatus")
            or data.get("authorizationStatus")
        )

        # token and amount
        auth_token = data.get("authorizationToken") or data.get("authToken") or data.get("token")
        auth_amount = data.get("authorizedAmount") or data.get("amount") or data.get("approvedAmount")
        exp = data.get("authExpiration") or data.get("expiration") or data.get("expiresAt")
        msg = data.get("message") or data.get("detail") or data.get("error") or ""

        if isinstance(auth_token, str):
            normalized["authorizationToken"] = auth_token

        if auth_amount is not None:
            try:
                normalized["authorizedAmount"] = float(auth_amount)
            except Exception:
                pass

        if isinstance(exp, str):
            normalized["authExpiration"] = exp

        if isinstance(msg, str):
            normalized["message"] = msg

        # Convert status into our 3-level outcome
        if isinstance(status_val, str):
            s = status_val.strip().lower()
            if s in ("approved", "authorized", "success", "ok"):
                normalized["status"] = "Approved"
            elif s in ("error", "server_error", "internal_error"):
                normalized["status"] = "Error"
            else:
                normalized["status"] = "Failed"

        # If provider didn't include a status string, infer from HTTP code
        if "status" not in data and resp.status_code in (200, 201):
            # If token exists, treat as approved; else failed
            normalized["status"] = "Approved" if normalized["authorizationToken"] else normalized["status"]

    else:
        # Non-JSON: infer from HTTP status and/or message text
        if resp.status_code in (200, 201):
            normalized["status"] = "Approved"
            normalized["message"] = "Payment Authorized"
        elif resp.status_code in (400, 401, 403, 422):
            normalized["status"] = "Failed"
            normalized["message"] = "Authorization Failed"
        else:
            normalized["status"] = "Failed"
            normalized["message"] = "Authorization Failed"

    # If explicitly non-2xx, keep it Failed unless 5xx handled above
    if resp.status_code >= 400 and resp.status_code < 500:
        normalized["status"] = "Failed"
        if not normalized["message"]:
            normalized["message"] = "Authorization Failed"

    return normalized