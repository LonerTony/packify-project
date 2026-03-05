# app.py
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

# -----------------------------
# Optional imports (repo-based)
# -----------------------------
try:
    from database.connection import get_connection  # expected in /database/connection.py
except Exception:
    get_connection = None

try:
    from services.payment_service import get_oauth_token, authorize_payment
except Exception:
    get_oauth_token = None
    authorize_payment = None

try:
    from services.logging_service import log_event
except Exception:
    log_event = None


# -----------------------------
# App Setup
# -----------------------------
def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

    # Simple health check
    @app.get("/health")
    def health():
        return {"status": "ok", "time": datetime.utcnow().isoformat()}

    # -----------------------------
    # Helpers
    # -----------------------------
    def _db():
        if get_connection is None:
            raise RuntimeError(
                "database/connection.py not found or get_connection() not importable."
            )
        return get_connection()

    def _log(order_id: Optional[str], event_type: str, message: str) -> None:
        # Prefer your logging_service.py, fallback to console
        if log_event:
            try:
                log_event(order_id=order_id, event_type=event_type, message=message)
                return
            except Exception:
                pass
        print(f"[{datetime.utcnow().isoformat()}] {event_type} order={order_id} {message}")

    def _new_order_id() -> str:
        # ORD + 8 chars; ex: ORD12AB34CD
        return "ORD" + uuid.uuid4().hex[:8].upper()

    def _to_money(val: Any) -> Decimal:
        # strict money conversion
        try:
            dec = Decimal(str(val)).quantize(Decimal("0.01"))
            if dec <= 0:
                raise ValueError("Amount must be > 0")
            return dec
        except (InvalidOperation, ValueError) as e:
            raise ValueError("Invalid amount") from e

    def _card_last4(card_number: str) -> str:
        digits = "".join(ch for ch in card_number if ch.isdigit())
        return digits[-4:] if len(digits) >= 4 else "????"

    # -----------------------------
    # Pages
    # -----------------------------
    @app.get("/")
    def root():
        return redirect(url_for("products"))

    @app.get("/products")
    def products():
        # You can render real products later; this keeps it simple.
        sample_products = [
            {"sku": "BP-001", "name": "Packify Trail Backpack", "price": "49.99"},
            {"sku": "BP-002", "name": "Packify City Backpack", "price": "64.99"},
            {"sku": "BP-003", "name": "Packify Travel Backpack", "price": "89.99"},
        ]
        return render_template("products.html", products=sample_products)

    @app.get("/checkout")
    def checkout():
        # A simple checkout page where JS will do validations/masking on the client.
        # OrderId and total can be generated server-side, or passed from products.
        order_id = request.args.get("order_id") or _new_order_id()
        total_amount = request.args.get("total_amount") or "50.00"
        return render_template("checkout.html", order_id=order_id, total_amount=total_amount)

    # -----------------------------
    # API: Create order + authorize payment
    # -----------------------------
    @app.post("/api/authorize")
    def api_authorize():
        """
        Expects JSON like:
        {
          "customer_fname": "...",
          "customer_lname": "...",
          "address": "...",
          "order_id": "ORD123...",
          "requested_amount": 50.00,
          "card": {
              "number": "1111-1111-1111-1111",
              "month": "08",
              "year": "2028",
              "ccv": "111"
          }
        }

        IMPORTANT: We do NOT store card number/ccv/month/year in DB (per requirements).
        """
        payload = request.get_json(silent=True) or {}
        order_id = payload.get("order_id") or _new_order_id()

        customer_fname = (payload.get("customer_fname") or "").strip()
        customer_lname = (payload.get("customer_lname") or "").strip()
        address = (payload.get("address") or "").strip()

        card = payload.get("card") or {}
        card_number = (card.get("number") or "").strip()
        card_month = (card.get("month") or "").strip()
        card_year = (card.get("year") or "").strip()
        ccv = (card.get("ccv") or "").strip()

        # Server-side sanity checks (client-side JS does the heavy lifting)
        if not customer_fname or not customer_lname or not address:
            return jsonify({"ok": False, "message": "Missing customer information."}), 400
        if not card_number or not card_month or not card_year or not ccv:
            return jsonify({"ok": False, "message": "Missing card fields."}), 400

        try:
            requested_amount = _to_money(payload.get("requested_amount"))
        except ValueError:
            return jsonify({"ok": False, "message": "Invalid requested amount."}), 400

        # Save ORDER first (status Pending)
        try:
            conn = _db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO orders (order_id, customer_fname, customer_lname, address, total_amount, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    customer_fname=VALUES(customer_fname),
                    customer_lname=VALUES(customer_lname),
                    address=VALUES(address),
                    total_amount=VALUES(total_amount)
                """,
                (
                    order_id,
                    customer_fname,
                    customer_lname,
                    address,
                    str(requested_amount),
                    "Pending",
                    datetime.utcnow(),
                ),
            )
            conn.commit()
            _log(order_id, "ORDER_CREATE", f"Order created/updated. amount={requested_amount}")
        except Exception as e:
            _log(order_id, "DB_ERROR", f"Failed to save order: {e}")
            return jsonify({"ok": False, "message": "Database error saving order."}), 500
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

        # Call Token API -> then Authorization API (mock endpoints)
        try:
            if not get_oauth_token or not authorize_payment:
                # Fallback response if services not created yet.
                # Replace by implementing services/payment_service.py.
                raise RuntimeError("payment_service not implemented")

            _log(order_id, "TOKEN_REQUEST", "Requesting OAuth token...")
            token = get_oauth_token()  # should call /oauth/token with merchantId/secretKey

            _log(order_id, "AUTH_REQUEST", "Calling authorize endpoint...")
            auth_resp = authorize_payment(
                token=token,
                order_id=order_id,
                card_number=card_number,
                card_month=card_month,
                card_year=card_year,
                ccv=ccv,
                requested_amount=float(requested_amount),
            )
            # Expected your service returns dict with keys like:
            # {
            #   "http_status": 200,
            #   "status": "Approved" | "Failed" | "Error",
            #   "authorizationToken": "abc123",
            #   "authorizedAmount": 50.0,
            #   "authExpiration": "2028-08-01T00:00:00Z",
            #   "message": "..."
            # }
        except Exception as e:
            _log(order_id, "PAYMENT_ERROR", f"Payment services unavailable or failed: {e}")

            # Update order to failed-system-error
            try:
                conn = _db()
                cur = conn.cursor()
                cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", ("Failed – System Error", order_id))
                conn.commit()
            except Exception:
                pass
            finally:
                try:
                    cur.close()
                    conn.close()
                except Exception:
                    pass

            return jsonify(
                {
                    "ok": False,
                    "order_id": order_id,
                    "message": "Payment service temporarily unavailable. Please try again later.",
                }
            ), 502

        # Interpret response & persist authorization attempt
        response_status = auth_resp.get("status") or "Failed"
        http_status = int(auth_resp.get("http_status") or 200)

        authorization_token = (auth_resp.get("authorizationToken") or "").strip()
        authorized_amount = auth_resp.get("authorizedAmount")
        message = auth_resp.get("message") or ""

        # Per spec: store concatenated token: {OrderId}_{authorization token}
        stored_auth_token = f"{order_id}_{authorization_token}" if authorization_token else f"{order_id}_NO_TOKEN"

        # Fake expiration if not provided
        auth_exp = auth_resp.get("authExpiration")
        try:
            # if service returns ISO string, you can parse it in service; keep simple here:
            auth_exp_dt = datetime.utcnow() + timedelta(days=7)
        except Exception:
            auth_exp_dt = datetime.utcnow() + timedelta(days=7)

        # Save to AUTHORIZATIONS table (success or failure)
        try:
            conn = _db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO authorizations
                    (order_id, auth_token, authorized_amount, auth_expiration, response_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    stored_auth_token,
                    str(authorized_amount if authorized_amount is not None else requested_amount),
                    auth_exp_dt,
                    response_status,
                    datetime.utcnow(),
                ),
            )

            # Update order status
            if response_status.lower() == "approved":
                new_status = "Authorized"
            elif http_status >= 500:
                new_status = "Failed – System Error"
            else:
                new_status = "Failed"

            cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (new_status, order_id))
            conn.commit()

            _log(order_id, "AUTH_RESPONSE", f"status={response_status} http={http_status} msg={message}")
        except Exception as e:
            _log(order_id, "DB_ERROR", f"Failed saving authorization: {e}")
            return jsonify({"ok": False, "order_id": order_id, "message": "Database error saving authorization."}), 500
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

        # Return minimal safe info (no PAN/CVV)
        return jsonify(
            {
                "ok": response_status.lower() == "approved",
                "order_id": order_id,
                "status": response_status,
                "order_status": "Authorized" if response_status.lower() == "approved" else "Failed",
                "authorized_amount": authorized_amount,
                "card_last4": _card_last4(card_number),
                "message": message or ("Payment Authorized" if response_status.lower() == "approved" else "Authorization Failed"),
            }
        ), (200 if response_status.lower() == "approved" else 402)

    # -----------------------------
    # Orders list page (sorting/filtering in UI; server supports query params too)
    # -----------------------------
    @app.get("/orders")
    def order_list():
        q = (request.args.get("q") or "").strip()  # simple text search
        status = (request.args.get("status") or "").strip()
        sort = (request.args.get("sort") or "created_at").strip()
        direction = (request.args.get("dir") or "desc").strip().lower()

        allowed_sort = {"order_id", "customer_fname", "customer_lname", "total_amount", "status", "created_at"}
        if sort not in allowed_sort:
            sort = "created_at"
        if direction not in {"asc", "desc"}:
            direction = "desc"

        # Build query safely
        where = []
        params = []

        if q:
            where.append("(order_id LIKE %s OR customer_fname LIKE %s OR customer_lname LIKE %s)")
            like = f"%{q}%"
            params.extend([like, like, like])

        if status:
            where.append("status = %s")
            params.append(status)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        sql = f"""
            SELECT order_id, customer_fname, customer_lname, address, total_amount, status, created_at
            FROM orders
            {where_sql}
            ORDER BY {sort} {direction}
            LIMIT 500
        """

        orders = []
        try:
            conn = _db()
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, tuple(params))
            orders = cur.fetchall()
        except Exception as e:
            _log(None, "DB_ERROR", f"Failed loading orders: {e}")
            flash("Database error loading orders.", "error")
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

        return render_template("order_list.html", orders=orders, q=q, status=status, sort=sort, direction=direction)

    # -----------------------------
    # Settlement page + API
    # -----------------------------
    @app.get("/settlement")
    def settlement_page():
        return render_template("settlement.html")

    @app.post("/api/settle")
    def api_settle():
        """
        Warehouse settlement:
        - requires order is Authorized
        - settlement_amount <= authorized_amount (latest approved auth)
        """
        data = request.get_json(silent=True) or {}
        order_id = (data.get("order_id") or "").strip()
        if not order_id:
            return jsonify({"ok": False, "message": "Order ID is required."}), 400

        try:
            settlement_amount = _to_money(data.get("settlement_amount"))
        except ValueError:
            return jsonify({"ok": False, "message": "Invalid settlement amount."}), 400

        try:
            conn = _db()
            cur = conn.cursor(dictionary=True)

            # Verify order status
            cur.execute("SELECT status FROM orders WHERE order_id=%s", (order_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"ok": False, "message": "Order not found."}), 404

            if (row["status"] or "").lower() != "authorized":
                return jsonify({"ok": False, "message": "Order is not authorized and cannot be settled."}), 409

            # Get latest approved authorization amount
            cur.execute(
                """
                SELECT authorized_amount
                FROM authorizations
                WHERE order_id=%s AND LOWER(response_status)='approved'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (order_id,),
            )
            auth = cur.fetchone()
            if not auth:
                return jsonify({"ok": False, "message": "No approved authorization found for this order."}), 409

            authorized_amount = Decimal(str(auth["authorized_amount"])).quantize(Decimal("0.01"))

            if settlement_amount > authorized_amount:
                return jsonify(
                    {
                        "ok": False,
                        "message": f"Settlement amount (${settlement_amount}) is greater than authorized amount (${authorized_amount}).",
                    }
                ), 422

            # Insert settlement + update order
            cur.execute(
                """
                INSERT INTO settlements (order_id, settlement_amount, created_at)
                VALUES (%s, %s, %s)
                """,
                (order_id, str(settlement_amount), datetime.utcnow()),
            )
            cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", ("Settled", order_id))
            conn.commit()

            _log(order_id, "SETTLEMENT_SUCCESS", f"Settled {settlement_amount} <= authorized {authorized_amount}")

            return jsonify(
                {
                    "ok": True,
                    "order_id": order_id,
                    "message": "Settlement successful.",
                    "settlement_amount": str(settlement_amount),
                    "authorized_amount": str(authorized_amount),
                }
            )
        except Exception as e:
            _log(order_id, "DB_ERROR", f"Settlement failed: {e}")
            return jsonify({"ok": False, "message": "Database error during settlement."}), 500
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    return app


app = create_app()

if __name__ == "__main__":
    # Local dev server
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=True)