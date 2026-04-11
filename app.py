import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from database.connection import get_connection
from services.payment_service import (
    PaymentServiceError,
    authorize_payment,
    get_oauth_token,
)

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

    try:
        from services.logging_service import log_event as external_log_event
    except Exception:
        external_log_event = None

    def log_event(order_id, event_type, message, level="INFO", metadata=None):
        try:
            if external_log_event:
                external_log_event(
                    order_id=order_id,
                    event_type=event_type,
                    message=message,
                    level=level,
                    metadata=metadata,
                )
                return

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO logs (order_id, event_type, level, message, metadata)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    event_type,
                    level,
                    message,
                    str(metadata) if metadata is not None else None,
                ),
            )

            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Logging failed: {e}")

    def get_json_payload():
        return request.get_json(silent=True) or request.form or {}

    def generate_order_id():
        return f"ORD{uuid.uuid4().hex[:9].upper()}"

    def to_decimal(value, default="0.00"):
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    def parse_auth_expiration(value):
        if not value:
            return None

        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")

        value = str(value).strip()

        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def fetch_orders(status=None, sort_by="created_at", sort_dir="DESC"):
        allowed_sort_columns = {
            "order_id": "o.order_id",
            "customer": "o.customer_lname",
            "amount": "o.total_amount",
            "status": "o.status",
            "created_at": "o.created_at",
        }

        sort_column = allowed_sort_columns.get(sort_by, "o.created_at")
        sort_direction = "ASC" if str(sort_dir).upper() == "ASC" else "DESC"

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        query = f"""
            SELECT
                o.order_id,
                o.customer_fname,
                o.customer_lname,
                o.address,
                o.total_amount,
                o.status,
                o.created_at,
                a.authorized_amount,
                a.response_status,
                a.auth_expiration
            FROM orders o
            LEFT JOIN (
                SELECT a1.*
                FROM authorizations a1
                INNER JOIN (
                    SELECT order_id, MAX(created_at) AS latest_created
                    FROM authorizations
                    GROUP BY order_id
                ) latest
                  ON a1.order_id = latest.order_id
                 AND a1.created_at = latest.latest_created
            ) a
              ON o.order_id = a.order_id
        """

        params = []
        if status and status.lower() != "all":
            query += " WHERE o.status = %s"
            params.append(status)

        query += f" ORDER BY {sort_column} {sort_direction}"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()
        return rows

    @app.route("/")
    def root():
        return render_template("home.html")

    @app.route("/products")
    def products():
        return render_template("products.html")

    @app.route("/cart")
    def cart():
        return render_template("cart.html")

    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        if request.method == "GET":
            return render_template("checkout.html")

        data = get_json_payload()

        first_name = str(data.get("firstName", "")).strip()
        last_name = str(data.get("lastName", "")).strip()
        address = str(data.get("address", "")).strip()
        zip_code = str(data.get("zip", "")).strip()

        card_number = str(data.get("cardNumber", "")).strip()
        month = str(data.get("month", "")).strip()
        year = str(data.get("year", "")).strip()
        cvv = str(data.get("cvv", "")).strip()

        requested_amount = to_decimal(data.get("amount"), "0.00")

        if not first_name or not last_name:
            return jsonify({"status": "Error", "message": "First and last name are required."}), 400

        if not address:
            return jsonify({"status": "Error", "message": "Address is required."}), 400

        if requested_amount <= 0:
            return jsonify({"status": "Error", "message": "Amount must be greater than zero."}), 400

        order_id = generate_order_id()

        conn = None
        cursor = None

        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO orders (
                    order_id,
                    customer_fname,
                    customer_lname,
                    address,
                    total_amount,
                    status
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    first_name,
                    last_name,
                    f"{address} {zip_code}".strip(),
                    requested_amount,
                    "Pending",
                ),
            )
            conn.commit()

            log_event(
                order_id,
                "ORDER_CREATED",
                "Order created successfully.",
                metadata={
                    "customer_fname": first_name,
                    "customer_lname": last_name,
                    "requested_amount": str(requested_amount),
                },
            )

            log_event(order_id, "TOKEN_REQUEST", "Requesting payment token.")
            token = get_oauth_token()
            log_event(order_id, "TOKEN_RESPONSE", "Payment token received successfully.")

            log_event(
                order_id,
                "AUTH_REQUEST",
                "Submitting authorization request.",
                metadata={"requested_amount": str(requested_amount)},
            )

            auth_resp = authorize_payment(
                order_id=order_id,
                card_number=card_number,
                card_month=month,
                card_year=year,
                cvv=cvv,
                requested_amount=float(requested_amount),
                token=token,
            )

            response_status = str(auth_resp.get("status", "Error")).strip()
            provider_status_code = int(auth_resp.get("provider_status_code") or 0)
            auth_token = auth_resp.get("authorizationToken")
            auth_expiration = parse_auth_expiration(auth_resp.get("authExpiration"))
            auth_message = auth_resp.get("message", "")
            authorized_amount = to_decimal(auth_resp.get("authorizedAmount"), "0.00")

            approved = response_status.lower() in {"approved", "authorized"}

            if not approved:
                authorized_amount = Decimal("0.00")

            order_status = "Authorized" if approved else "Failed"

            composite_auth_token = f"{order_id}_{auth_token}" if auth_token else None

            cursor.execute(
                """
                INSERT INTO authorizations (
                    order_id,
                    auth_token,
                    authorized_amount,
                    auth_expiration,
                    response_status
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    composite_auth_token,
                    authorized_amount,
                    auth_expiration,
                    response_status,
                ),
            )

            cursor.execute(
                """
                UPDATE orders
                SET status = %s
                WHERE order_id = %s
                """,
                (order_status, order_id),
            )

            conn.commit()

            log_event(
                order_id,
                "AUTH_RESPONSE",
                auth_message or "Authorization response received.",
                level="INFO" if approved else "WARNING",
                metadata={
                    "response_status": response_status,
                    "provider_status_code": provider_status_code,
                    "authorized_amount": str(authorized_amount),
                    "order_status": order_status,
                },
            )

            if approved:
                return jsonify(
                    {
                        "status": "Authorized",
                        "order_id": order_id,
                        "order_status": order_status,
                        "authorizedAmount": float(authorized_amount),
                        "amount": float(authorized_amount),
                        "message": auth_message or "Payment authorized successfully.",
                    }
                ), 200

            return jsonify(
                {
                    "status": "Failed",
                    "order_id": order_id,
                    "order_status": order_status,
                    "authorizedAmount": 0.0,
                    "amount": 0.0,
                    "message": auth_message or "Payment authorization failed.",
                }
            ), 200

        except PaymentServiceError as e:
            if conn:
                conn.rollback()

            try:
                if conn and cursor:
                    cursor.execute(
                        "UPDATE orders SET status = %s WHERE order_id = %s",
                        ("Error", order_id),
                    )
                    conn.commit()
            except Exception:
                pass

            log_event(
                order_id,
                "PAYMENT_SERVICE_ERROR",
                str(e),
                level="ERROR",
            )

            return jsonify(
                {
                    "status": "Error",
                    "order_id": order_id,
                    "message": str(e),
                }
            ), 502

        except Exception as e:
            if conn:
                conn.rollback()

            try:
                if conn and cursor:
                    cursor.execute(
                        "UPDATE orders SET status = %s WHERE order_id = %s",
                        ("Error", order_id),
                    )
                    conn.commit()
            except Exception:
                pass

            log_event(
                order_id,
                "SYSTEM_ERROR",
                str(e),
                level="ERROR",
            )

            print("CHECKOUT ERROR:", str(e))

            return jsonify(
                {
                    "status": "Error",
                    "order_id": order_id,
                    "message": str(e)
                }
            ), 500

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    @app.route("/orders")
    def order_list():
        status = request.args.get("status", "all")
        sort_by = request.args.get("sort_by", "created_at")
        sort_dir = request.args.get("sort_dir", "DESC")

        try:
            orders = fetch_orders(status=status, sort_by=sort_by, sort_dir=sort_dir)
            return render_template("order_list.html", orders=orders)
        except Exception as e:
            log_event(None, "ORDER_LIST_ERROR", str(e), level="ERROR")
            return render_template("order_list.html", orders=[], error="Unable to load orders.")

    @app.route("/settlement", methods=["GET", "POST"])
    def settlement():
        if request.method == "GET":
            return render_template("settlement.html")

        data = get_json_payload()
        order_id = str(data.get("order_id", "")).strip()
        settlement_amount = to_decimal(data.get("settlement_amount"), "0.00")

        if not order_id:
            return jsonify({"status": "Error", "message": "Order ID is required."}), 400

        if settlement_amount <= 0:
            return jsonify({"status": "Error", "message": "Settlement amount must be greater than 0."}), 400

        conn = None
        cursor = None

        try:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True)

            log_event(
                order_id,
                "SETTLEMENT_ATTEMPT",
                "Settlement requested.",
                metadata={"settlement_amount": str(settlement_amount)},
            )

            cursor.execute(
                """
                SELECT order_id, status, total_amount
                FROM orders
                WHERE order_id = %s
                """,
                (order_id,),
            )
            order_row = cursor.fetchone()

            if not order_row:
                return jsonify({"status": "Error", "message": "Order not found."}), 404

            cursor.execute(
                """
                SELECT authorized_amount, response_status, auth_expiration, created_at
                FROM authorizations
                WHERE order_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (order_id,),
            )
            auth_row = cursor.fetchone()

            if not auth_row:
                return jsonify(
                    {"status": "Error", "message": "No authorization record found for this order."}
                ), 400

            latest_status = str(auth_row.get("response_status", "")).strip().lower()
            authorized_amount = to_decimal(auth_row.get("authorized_amount"), "0.00")

            if latest_status not in {"approved", "authorized"} and str(order_row.get("status", "")).lower() != "authorized":
                return jsonify(
                    {"status": "Error", "message": "This order is not authorized for settlement."}
                ), 400

            if settlement_amount > authorized_amount:
                return jsonify(
                    {
                        "status": "Error",
                        "message": "Settlement amount cannot exceed the authorized amount.",
                    }
                ), 400

            cursor.execute(
                """
                SELECT settlement_id
                FROM settlements
                WHERE order_id = %s
                LIMIT 1
                """,
                (order_id,),
            )
            existing_settlement = cursor.fetchone()

            if existing_settlement:
                return jsonify(
                    {"status": "Error", "message": "This order has already been settled."}
                ), 400

            cursor.execute(
                """
                INSERT INTO settlements (order_id, settlement_amount)
                VALUES (%s, %s)
                """,
                (order_id, settlement_amount),
            )

            cursor.execute(
                """
                UPDATE orders
                SET status = %s
                WHERE order_id = %s
                """,
                ("Settled", order_id),
            )

            conn.commit()

            log_event(
                order_id,
                "SETTLEMENT_SUCCESS",
                "Settlement completed successfully.",
                metadata={"settlement_amount": str(settlement_amount)},
            )

            return jsonify(
                {
                    "status": "Success",
                    "order_id": order_id,
                    "settlement_amount": float(settlement_amount),
                    "message": f"Settlement completed for order {order_id}.",
                }
            ), 200

        except Exception as e:
            if conn:
                conn.rollback()

            log_event(
                order_id,
                "SETTLEMENT_ERROR",
                str(e),
                level="ERROR",
            )

            print("SETTLEMENT ERROR:", str(e))

            return jsonify(
                {
                    "status": "Error",
                    "message": str(e),
                }
            ), 500

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("FLASK_PORT", 5001)))
