import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()


class PaymentServiceError(Exception):
    """Raised when the payment service cannot complete a required step."""
    pass


TOKEN_URL = os.getenv("PAYMENT_TOKEN_URL")
AUTHORIZE_URL = os.getenv("PAYMENT_AUTHORIZE_URL")
MERCHANT_ID = os.getenv("PAYMENT_MERCHANT_ID")
SECRET_KEY = os.getenv("PAYMENT_SECRET_KEY")
REQUEST_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", 15))


def _validate_config() -> None:
    missing = []

    if not TOKEN_URL:
        missing.append("PAYMENT_TOKEN_URL")
    if not AUTHORIZE_URL:
        missing.append("PAYMENT_AUTHORIZE_URL")
    if not MERCHANT_ID:
        missing.append("PAYMENT_MERCHANT_ID")
    if not SECRET_KEY:
        missing.append("PAYMENT_SECRET_KEY")

    if missing:
        raise PaymentServiceError(
            f"Missing required payment configuration: {', '.join(missing)}"
        )


def _safe_json(response: requests.Response) -> Optional[Dict[str, Any]]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def _normalize_status(raw_status: Optional[str], http_status: int) -> str:
    if http_status >= 500:
        return "Error"

    status = (raw_status or "").strip().lower()

    approved_values = {
        "approved",
        "authorized",
        "success",
        "succeeded",
        "ok",
    }
    failed_values = {
        "failed",
        "declined",
        "denied",
        "rejected",
        "invalid",
        "insufficient_funds",
        "insufficient funds",
    }
    error_values = {
        "error",
        "server_error",
        "system_error",
    }

    if status in approved_values:
        return "Approved"
    if status in failed_values:
        return "Failed"
    if status in error_values:
        return "Error"

    if 200 <= http_status < 300:
        return "Failed"

    return "Error"


def get_oauth_token() -> str:
    _validate_config()

    payload = {
        "merchantId": MERCHANT_ID,
        "secretKey": SECRET_KEY,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            TOKEN_URL,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise PaymentServiceError(f"Token request failed: {e}") from e

    data = _safe_json(response)

    if response.status_code >= 500:
        raise PaymentServiceError(
            f"Payment token endpoint server error ({response.status_code})."
        )

    if response.status_code < 200 or response.status_code >= 300:
        message = "Unable to retrieve payment token."
        if data and data.get("message"):
            message = str(data["message"])
        elif response.text:
            message = response.text.strip()
        raise PaymentServiceError(
            f"Token request failed ({response.status_code}): {message}"
        )

    if not data:
        raise PaymentServiceError("Token response was not valid JSON.")

    token = (
        data.get("access_token")
        or data.get("token")
        or data.get("authToken")
        or data.get("authorizationToken")
    )

    if not token:
        raise PaymentServiceError("Token response did not contain an access token.")

    return str(token)


def authorize_payment(
    order_id: str,
    card_number: str,
    card_month: str,
    card_year: str,
    cvv: str,
    requested_amount: float,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    _validate_config()

    if not order_id:
        return {
            "status": "Error",
            "authorizationToken": None,
            "authorizedAmount": 0.0,
            "authExpiration": None,
            "message": "Order ID is required.",
            "provider_status_code": 0,
            "raw": None,
        }

    try:
        amount = float(requested_amount)
    except (TypeError, ValueError):
        return {
            "status": "Error",
            "authorizationToken": None,
            "authorizedAmount": 0.0,
            "authExpiration": None,
            "message": "Requested amount is invalid.",
            "provider_status_code": 0,
            "raw": None,
        }

    if amount <= 0:
        return {
            "status": "Error",
            "authorizationToken": None,
            "authorizedAmount": 0.0,
            "authExpiration": None,
            "message": "Requested amount must be greater than zero.",
            "provider_status_code": 0,
            "raw": None,
        }

    if token is None:
        try:
            token = get_oauth_token()
        except PaymentServiceError as e:
            return {
                "status": "Error",
                "authorizationToken": None,
                "authorizedAmount": 0.0,
                "authExpiration": None,
                "message": str(e),
                "provider_status_code": 0,
                "raw": None,
            }

    payload = {
        "OrderId": str(order_id),
        "CardDetails": {
            "CardNumber": str(card_number),
            "CardMonth": str(card_month),
            "CardYear": str(card_year),
            "CCV": str(cvv),
        },
        "RequestedAmount": amount,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": token,
    }

    try:
        response = requests.post(
            AUTHORIZE_URL,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        masked_headers = dict(headers)
        if masked_headers.get("Authorization"):
            masked_headers["Authorization"] = "***MASKED***"

        print("------ AUTH DEBUG ------")
        print("PAYLOAD:", payload)
        print("HEADERS:", masked_headers)
        print("STATUS CODE:", response.status_code)
        print("RAW RESPONSE:", response.text)
        print("------------------------")

    except requests.RequestException as e:
        return {
            "status": "Error",
            "authorizationToken": None,
            "authorizedAmount": 0.0,
            "authExpiration": None,
            "message": f"Authorization request failed: {e}",
            "provider_status_code": 0,
            "raw": None,
        }

    data = _safe_json(response)
    print("PARSED RESPONSE:", data)
    provider_status_code = response.status_code

    if data:
        success_value = data.get("Success")

        if success_value is True:
            raw_status = "approved"
        elif success_value is False:
            raw_status = "failed"
        else:
            raw_status = (
                data.get("status")
                or data.get("responseStatus")
                or data.get("authorizationStatus")
                or data.get("result")
            )

        auth_token = (
            data.get("AuthorizationToken")
            or data.get("authorizationToken")
            or data.get("authToken")
            or data.get("token")
        )

        auth_expiration = (
            data.get("TokenExpirationDate")
            or data.get("authExpiration")
            or data.get("expiration")
            or data.get("expiresAt")
        )

        provider_amount = (
            data.get("AuthorizedAmount")
            or data.get("authorizedAmount")
            or data.get("amount")
            or data.get("approvedAmount")
        )

        message = (
            data.get("Reason")
            or data.get("message")
            or data.get("responseMessage")
            or data.get("detail")
            or ""
        )
    else:
        raw_status = None
        auth_token = None
        auth_expiration = None
        provider_amount = None
        message = (response.text or "").strip()

    normalized_status = _normalize_status(raw_status, provider_status_code)

    if normalized_status == "Approved":
        try:
            final_amount = float(provider_amount) if provider_amount is not None else amount
        except (TypeError, ValueError):
            final_amount = amount
    else:
        final_amount = 0.0

    if not message:
        if normalized_status == "Approved":
            message = "Payment authorized successfully."
        elif normalized_status == "Failed":
            message = "Payment authorization was declined."
        else:
            message = "Payment service is temporarily unavailable."

    stored_token = f"{order_id}_{auth_token}" if auth_token else None

    return {
        "status": normalized_status,
        "authorizationToken": stored_token,
        "authorizedAmount": final_amount,
        "authExpiration": str(auth_expiration) if auth_expiration else None,
        "message": message,
        "provider_status_code": provider_status_code,
        "raw": data if data is not None else ((response.text or "").strip() or None),
    }