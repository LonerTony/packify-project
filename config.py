# config.py
# Configuration settings for Packify E-Commerce Payment Simulation

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """
    Base configuration class
    """

    # -----------------------------
    # Flask Settings
    # -----------------------------
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev_secret_key")
    DEBUG = True

    # -----------------------------
    # Database Configuration
    # -----------------------------
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "NewPassword123!")
    DB_NAME = os.getenv("DB_NAME", "packify")
    DB_PORT = int(os.getenv("DB_PORT", 3306))

    # -----------------------------
    # Payment API Configuration
    # -----------------------------
    TOKEN_API_URL = os.getenv(
        "TOKEN_API_URL",
        "https://capstoneproject.proxy.beeceptor.com/oauth/token"
    )

    AUTHORIZATION_API_URL = os.getenv(
        "AUTHORIZATION_API_URL",
        "https://capstoneproject.proxy.beeceptor.com/authorize"
    )

    # -----------------------------
    # Merchant Credentials
    # -----------------------------
    MERCHANT_ID = os.getenv("MERCHANT_ID", "ksuCapstone")
    SECRET_KEY_API = os.getenv("SECRET_KEY_API", "P@ymentP@ss!")

    # -----------------------------
    # Payment Settings
    # -----------------------------
    PAYMENT_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", 15))

    # -----------------------------
    # Logging Settings
    # -----------------------------
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # -----------------------------
    # Application Settings
    # -----------------------------
    ORDER_PREFIX = "ORD"
    AUTH_TOKEN_SEPARATOR = "_"