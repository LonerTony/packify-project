import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

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
            print("Logging failed:", str(e))

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

    def get_cart_items_from_payload(data):
        raw_items = (
            data.get("cartItems")
            or data.get("cart_items")
            or data.get("items")
            or []
        )

        items = []

        if not isinstance(raw_items, list):
            return items

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            name = str(
                item.get("name")
                or item.get("product_name")
                or item.get("productName")
                or ""
            ).strip()

            quantity = item.get("quantity", item.get("qty", 1))
            price = item.get("price", item.get("unitPrice", item.get("amount", 0)))

            try:
                quantity = int(quantity)
            except (TypeError, ValueError):
                quantity = 1

            try:
                price = Decimal(str(price))
            except (InvalidOperation, TypeError, ValueError):
                price = Decimal("0.00")

            if name and quantity > 0:
                items.append(
                    {
                        "name": name,
                        "quantity": quantity,
                        "price": price,
                    }
                )

        return items

    def calculate_cart_total(cart_items):
        total = Decimal("0.00")

        for item in cart_items:
            total += to_decimal(item.get("price"), "0.00") * to_decimal(item.get("quantity"), "0")

        return total

    def check_inventory_availability(cart_items):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        unavailable = []

        try:
            for item in cart_items:
                cursor.execute(
                    """
                    SELECT sku, product_name, stock
                    FROM inventory
                    WHERE LOWER(product_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (item["name"],),
                )

                row = cursor.fetchone()

                if not row:
                    unavailable.append(f"{item['name']} is not in inventory.")
                    continue

                if int(row["stock"]) < int(item["quantity"]):
                    unavailable.append(
                        f"{item['name']} only has {row['stock']} left, but {item['quantity']} requested."
                    )

            return unavailable

        finally:
            cursor.close()
            conn.close()

    def reduce_inventory(cursor, cart_items):
        for item in cart_items:
            cursor.execute(
                """
                UPDATE inventory
                SET stock = stock - %s
                WHERE LOWER(product_name) = LOWER(%s)
                  AND stock >= %s
                LIMIT 1
                """,
                (item["quantity"], item["name"], item["quantity"]),
            )

            if cursor.rowcount == 0:
                raise Exception(f"Unable to reduce inventory for {item['name']}.")

    def fetch_inventory():
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)

        try:
            cursor.execute(
                """
                SELECT sku, product_name AS name, brand, category, stock
                FROM inventory
                ORDER BY brand, product_name
                """
            )
            return cursor.fetchall()

        finally:
            cursor.close()
            conn.close()

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
        cursor = conn.cursor(dictionary=True, buffered=True)

        try:
            query = """
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
            return cursor.fetchall()

        finally:
            cursor.close()
            conn.close()

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
        cart_items = get_cart_items_from_payload(data)

        first_name = str(data.get("firstName", "")).strip()
        last_name = str(data.get("lastName", "")).strip()
        address = str(data.get("address", "")).strip()
        zip_code = str(data.get("zip", "")).strip()

        card_number = str(data.get("cardNumber", "")).strip()
        month = str(data.get("month", "")).strip()
        year = str(data.get("year", "")).strip()
        cvv = str(data.get("cvv", "")).strip()

        requested_amount = to_decimal(data.get("amount"), "0.00")
        calculated_total = calculate_cart_total(cart_items)

        print("===== CHECKOUT DEBUG =====")
        print("CHECKOUT DATA:", data)
        print("CART ITEMS RECEIVED:", cart_items)
        print("AMOUNT RECEIVED:", requested_amount)
        print("CALCULATED TOTAL:", calculated_total)

        if not first_name or not last_name:
            return jsonify({"status": "Error", "message": "First and last name are required."}), 400

        if not address:
            return jsonify({"status": "Error", "message": "Address is required."}), 400

        if not cart_items:
            return jsonify({"status": "Error", "message": "Cart items are required."}), 400

        if requested_amount <= 0 and calculated_total > 0:
            requested_amount = calculated_total

        if requested_amount <= 0:
            return jsonify({"status": "Error", "message": "Amount must be greater than zero."}), 400

        inventory_issues = check_inventory_availability(cart_items)

        if inventory_issues:
            return jsonify(
                {
                    "status": "Error",
                    "message": "Inventory unavailable.",
                    "details": inventory_issues,
                }
            ), 400

        order_id = generate_order_id()
        conn = None
        cursor = None

        try:
            conn = get_connection()
            cursor = conn.cursor(buffered=True)

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

            for item in cart_items:
                cursor.execute(
                    """
                    INSERT INTO order_items (order_id, product_name, quantity)
                    VALUES (%s, %s, %s)
                    """,
                    (order_id, item["name"], item["quantity"]),
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

            token = get_oauth_token()

            auth_resp = authorize_payment(
                order_id=order_id,
                card_number=card_number,
                card_month=month,
                card_year=year,
                cvv=cvv,
                requested_amount=float(requested_amount),
                token=token,
            )

            print("AUTH RESPONSE:", auth_resp)

            response_status = str(auth_resp.get("status", "Error")).strip()
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
                    response_status,
                    response_message
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    composite_auth_token,
                    authorized_amount,
                    auth_expiration,
                    response_status,
                    auth_message,
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

            if approved:
                reduce_inventory(cursor, cart_items)

            conn.commit()

            log_event(
                order_id,
                "AUTH_RESPONSE",
                auth_message or "Authorization response received.",
                level="INFO" if approved else "WARNING",
                metadata={
                    "response_status": response_status,
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

            log_event(order_id, "PAYMENT_SERVICE_ERROR", str(e), level="ERROR")

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

            log_event(order_id, "SYSTEM_ERROR", str(e), level="ERROR")
            print("CHECKOUT ERROR:", str(e))

            return jsonify(
                {
                    "status": "Error",
                    "order_id": order_id,
                    "message": str(e),
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
            print("ORDER LIST ERROR:", str(e))
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
            cursor = conn.cursor(dictionary=True, buffered=True)

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

            log_event(order_id, "SETTLEMENT_ERROR", str(e), level="ERROR")
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

    @app.route("/inventory")
    def inventory():
        try:
            inventory_items = fetch_inventory()
            return render_template("inventory.html", inventory=inventory_items)
        except Exception as e:
            print("INVENTORY LOAD ERROR:", str(e))
            log_event(None, "INVENTORY_LOAD_ERROR", str(e), level="ERROR")
            return render_template("inventory.html", inventory=[])

    @app.route("/returns")
    def returns():
        conn = None
        cursor = None

        try:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True, buffered=True)

            cursor.execute(
                """
                SELECT return_id, order_id, item, quantity, reason, status, created_at
                FROM returns
                ORDER BY return_id DESC
                """
            )

            returns_data = cursor.fetchall()

            return render_template("returns.html", returns=returns_data)

        except Exception as e:
            print("RETURNS LOAD ERROR:", str(e))
            log_event(None, "RETURNS_LOAD_ERROR", str(e), level="ERROR")
            return render_template("returns.html", returns=[])

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    @app.route("/validate_return_order", methods=["POST"])
    def validate_return_order():
        data = get_json_payload()
        order_id = str(data.get("order_id", "")).strip()

        if not order_id:
            return jsonify({"status": "Error", "message": "Order ID is required."}), 400

        conn = None
        cursor = None

        try:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True, buffered=True)

            cursor.execute(
                """
                SELECT order_id, status
                FROM orders
                WHERE order_id = %s
                """,
                (order_id,),
            )

            order = cursor.fetchone()

            if not order:
                return jsonify({"status": "Error", "message": "Order not found."}), 404

            order_status = str(order["status"]).strip().lower()

            if order_status not in ["authorized", "settled"]:
                return jsonify(
                    {
                        "status": "Error",
                        "message": "Only authorized or settled orders can be returned.",
                    }
                ), 400

            cursor.execute(
                """
                SELECT
                    oi.product_name,
                    oi.quantity AS purchased_qty,
                    COALESCE(SUM(r.quantity), 0) AS returned_qty,
                    oi.quantity - COALESCE(SUM(r.quantity), 0) AS remaining_qty
                FROM order_items oi
                LEFT JOIN returns r
                  ON oi.order_id = r.order_id
                 AND LOWER(oi.product_name) = LOWER(r.item)
                WHERE oi.order_id = %s
                GROUP BY oi.product_name, oi.quantity
                HAVING remaining_qty > 0
                ORDER BY oi.product_name
                """,
                (order_id,),
            )

            items = cursor.fetchall()

            return jsonify(
                {
                    "status": "Success",
                    "message": f"Order {order_id} is valid for return.",
                    "items": items,
                }
            ), 200

        except Exception as e:
            print("VALIDATE RETURN ERROR:", str(e))
            return jsonify({"status": "Error", "message": str(e)}), 500

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    @app.route("/process_return", methods=["POST"])
    def process_return():
        conn = None
        cursor = None

        data = get_json_payload()

        order_id = str(data.get("order_id", "")).strip()
        product_name = str(data.get("product_name", "")).strip()
        reason = str(data.get("reason", "")).strip()
        notes = str(data.get("notes", "")).strip()
        quantity = data.get("quantity", 1)

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 1

        if not order_id:
            return jsonify({"status": "Error", "message": "Order ID is required."}), 400

        if not product_name:
            return jsonify({"status": "Error", "message": "Product name is required."}), 400

        if not reason:
            return jsonify({"status": "Error", "message": "Return reason is required."}), 400

        if quantity <= 0:
            return jsonify({"status": "Error", "message": "Quantity must be greater than 0."}), 400

        try:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True, buffered=True)

            cursor.execute(
                """
                SELECT order_id, status
                FROM orders
                WHERE order_id = %s
                """,
                (order_id,),
            )

            order = cursor.fetchone()

            if not order:
                return jsonify({"status": "Error", "message": "Order not found."}), 404

            if str(order["status"]).strip().lower() not in ["authorized", "settled"]:
                return jsonify(
                    {
                        "status": "Error",
                        "message": "Only authorized or settled orders can be returned.",
                    }
                ), 400

            cursor.execute(
                """
                SELECT quantity
                FROM order_items
                WHERE order_id = %s
                  AND LOWER(product_name) = LOWER(%s)
                LIMIT 1
                """,
                (order_id, product_name),
            )

            order_item = cursor.fetchone()

            if not order_item:
                return jsonify(
                    {
                        "status": "Error",
                        "message": "That product was not found on this order.",
                    }
                ), 400

            purchased_qty = int(order_item["quantity"])

            cursor.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS returned_qty
                FROM returns
                WHERE order_id = %s
                  AND LOWER(item) = LOWER(%s)
                """,
                (order_id, product_name),
            )

            returned_row = cursor.fetchone()
            returned_qty = int(returned_row["returned_qty"] or 0)

            remaining_qty = purchased_qty - returned_qty

            if remaining_qty <= 0:
                return jsonify(
                    {
                        "status": "Error",
                        "message": "This item has already been fully returned.",
                    }
                ), 400

            if quantity > remaining_qty:
                return jsonify(
                    {
                        "status": "Error",
                        "message": f"You can only return {remaining_qty} more of this item.",
                    }
                ), 400

            final_reason = reason
            if notes:
                final_reason = f"{reason} - Notes: {notes}"

            cursor.execute(
                """
                INSERT INTO returns (order_id, item, quantity, reason, status)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, product_name, quantity, final_reason, "Pending"),
            )

            cursor.execute(
                """
                UPDATE inventory
                SET stock = stock + %s
                WHERE LOWER(product_name) = LOWER(%s)
                LIMIT 1
                """,
                (quantity, product_name),
            )

            conn.commit()

            log_event(
                order_id,
                "RETURN_SUBMITTED",
                f"Return submitted for {quantity} {product_name}.",
                metadata={
                    "product_name": product_name,
                    "quantity": quantity,
                    "reason": final_reason,
                },
            )

            return jsonify(
                {
                    "status": "Success",
                    "message": f"Return submitted for {quantity} {product_name}(s) on order {order_id}.",
                }
            ), 200

        except Exception as e:
            if conn:
                conn.rollback()

            print("RETURN ERROR:", str(e))

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

    @app.route("/reset_orders", methods=["POST"])
    def reset_orders():
        conn = None
        cursor = None

        try:
            conn = get_connection()
            cursor = conn.cursor(buffered=True)

            cursor.execute("DELETE FROM logs WHERE order_id IS NOT NULL")
            cursor.execute("DELETE FROM returns")
            cursor.execute("DELETE FROM settlements")
            cursor.execute("DELETE FROM authorizations")
            cursor.execute("DELETE FROM order_items")
            cursor.execute("DELETE FROM orders")

            conn.commit()

            return redirect(url_for("order_list"))

        except Exception as e:
            if conn:
                conn.rollback()

            log_event(None, "RESET_ORDERS_ERROR", str(e), level="ERROR")

            return f"Error resetting orders: {str(e)}", 500

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("FLASK_PORT", 5001)))