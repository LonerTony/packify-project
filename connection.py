# database/connection.py

import os
import mysql.connector
from mysql.connector import Error


def get_connection():
    """
    Creates and returns a MySQL database connection.
    Database credentials are read from environment variables.
    """

    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "packify_db"),
            port=os.getenv("DB_PORT", 3306)
        )

        if connection.is_connected():
            return connection

    except Error as e:
        print("Database connection error:", e)
        raise