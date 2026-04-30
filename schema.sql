CREATE DATABASE IF NOT EXISTS packify;
USE packify;

CREATE TABLE IF NOT EXISTS orders (
  order_id         VARCHAR(20) NOT NULL,
  customer_fname   VARCHAR(50) NOT NULL,
  customer_lname   VARCHAR(50) NOT NULL,
  address          VARCHAR(255) NOT NULL,
  total_amount     DECIMAL(10,2) NOT NULL,
  status           VARCHAR(50) NOT NULL DEFAULT 'Pending',
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (order_id),
  INDEX idx_orders_status (status),
  INDEX idx_orders_created (created_at),
  INDEX idx_orders_customer (customer_lname, customer_fname)
);

CREATE TABLE IF NOT EXISTS authorizations (
  auth_id            BIGINT NOT NULL AUTO_INCREMENT,
  order_id           VARCHAR(20) NOT NULL,
  auth_token         VARCHAR(255) NULL,
  authorized_amount  DECIMAL(10,2) NOT NULL,
  auth_expiration    DATETIME NULL,
  response_status    VARCHAR(20) NOT NULL,
  response_message   VARCHAR(255) NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (auth_id),
  INDEX idx_auth_order (order_id),
  INDEX idx_auth_status (response_status),
  CONSTRAINT fk_auth_order
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settlements (
  settlement_id      BIGINT NOT NULL AUTO_INCREMENT,
  order_id           VARCHAR(20) NOT NULL,
  settlement_amount  DECIMAL(10,2) NOT NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (settlement_id),
  UNIQUE KEY uniq_settlement_order (order_id),
  INDEX idx_settle_created (created_at),
  CONSTRAINT fk_settle_order
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS logs (
  log_id         BIGINT NOT NULL AUTO_INCREMENT,
  order_id       VARCHAR(20) NULL,
  event_type     VARCHAR(100) NOT NULL,
  level          VARCHAR(20) NOT NULL DEFAULT 'INFO',
  message        TEXT NOT NULL,
  metadata       TEXT NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  INDEX idx_logs_order (order_id),
  INDEX idx_logs_event (event_type),
  INDEX idx_logs_created (created_at),
  CONSTRAINT fk_logs_order
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
    ON DELETE SET NULL
);

DELETE FROM logs WHERE order_id IS NOT NULL;
DELETE FROM settlements;
DELETE FROM authorizations;
DELETE FROM orders;

CREATE TABLE IF NOT EXISTS order_items (
  item_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id VARCHAR(20),
  product_name VARCHAR(255),
  quantity INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory (
  sku VARCHAR(50) PRIMARY KEY,
  product_name VARCHAR(255),
  brand VARCHAR(100),
  category VARCHAR(100),
  stock INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS returns (
  return_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id VARCHAR(20),
  item VARCHAR(255),
  quantity INT,
  reason VARCHAR(255),
  status VARCHAR(50) DEFAULT 'Pending',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);