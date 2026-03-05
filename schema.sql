-- database/schema.sql
-- Packify – E-Commerce Payment Simulation
-- MySQL schema for orders, authorizations, settlements, logs
-- Notes:
--  - Do NOT store full card number, CVV, or expiration in any table.
--  - Authorization token stored as: {OrderId}_{authorizationToken}

CREATE DATABASE IF NOT EXISTS packify_db;
USE packify_db;

-- -----------------------------
-- ORDERS
-- -----------------------------
CREATE TABLE IF NOT EXISTS orders (
  order_id        VARCHAR(20)  NOT NULL,
  customer_fname  VARCHAR(50)  NOT NULL,
  customer_lname  VARCHAR(50)  NOT NULL,
  address         VARCHAR(255) NOT NULL,
  total_amount    DECIMAL(10,2) NOT NULL,
  status          VARCHAR(50)  NOT NULL DEFAULT 'Pending',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (order_id),
  INDEX idx_orders_status (status),
  INDEX idx_orders_created (created_at),
  INDEX idx_orders_customer (customer_lname, customer_fname)
);

-- -----------------------------
-- AUTHORIZATIONS
-- Stores each authorization attempt (approved/failed/error)
-- -----------------------------
CREATE TABLE IF NOT EXISTS authorizations (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  order_id        VARCHAR(20)  NOT NULL,
  auth_token      VARCHAR(255) NOT NULL,
  authorized_amount DECIMAL(10,2) NOT NULL,
  auth_expiration DATETIME     NULL,
  response_status VARCHAR(20)  NOT NULL,  -- Approved / Failed / Error
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_auth_order (order_id),
  INDEX idx_auth_status (response_status),
  CONSTRAINT fk_auth_order
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
    ON DELETE CASCADE
);

-- -----------------------------
-- SETTLEMENTS
-- One order can be settled once (typical). If you want multiple partial settlements,
-- remove the UNIQUE constraint and handle totals in app logic.
-- -----------------------------
CREATE TABLE IF NOT EXISTS settlements (
  id               BIGINT       NOT NULL AUTO_INCREMENT,
  order_id         VARCHAR(20)  NOT NULL,
  settlement_amount DECIMAL(10,2) NOT NULL,
  created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_settlement_order (order_id),
  INDEX idx_settle_created (created_at),
  CONSTRAINT fk_settle_order
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
    ON DELETE CASCADE
);

-- -----------------------------
-- LOGS
-- Application events (no PAN/CVV/exp)
-- metadata is optional; stored as TEXT for compatibility.
-- -----------------------------
CREATE TABLE IF NOT EXISTS logs (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  order_id    VARCHAR(20)  NULL,
  event_type  VARCHAR(100) NOT NULL,
  level       VARCHAR(20)  NOT NULL DEFAULT 'INFO',
  message     TEXT         NOT NULL,
  metadata    TEXT         NULL,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_logs_order (order_id),
  INDEX idx_logs_event (event_type),
  INDEX idx_logs_created (created_at)
);

-- -----------------------------
-- Optional: seed data (safe)
-- -----------------------------
-- INSERT INTO orders (order_id, customer_fname, customer_lname, address, total_amount, status)
-- VALUES ('ORDDEMO001', 'Demo', 'User', '123 Main St', 50.00, 'Pending');