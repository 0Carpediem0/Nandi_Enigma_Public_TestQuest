"""
Точка входа для запуска сервиса (в т.ч. из Docker).
Проверка почты и простой пример вызова IMAP/SMTP.
"""

import os
import json

# Загружаем .env если есть (для локального запуска без Docker)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from email_service import fetch_recent_emails, send_email, check_connection, DEFAULT_STUB_EMAIL


def main():
    print("Email service (stub:", DEFAULT_STUB_EMAIL, ")")
    print("--- check_connection ---")
    conn = check_connection()
    print(json.dumps(conn, indent=2, ensure_ascii=False))

    print("\n--- fetch_recent_emails(limit=3) ---")
    emails = fetch_recent_emails(limit=3)
    print(json.dumps(emails, indent=2, ensure_ascii=False))

    # Раскомментировать для проверки отправки (осторожно — реальная отправка)
    # print("\n--- send_email (example) ---")
    # r = send_email("recipient@example.com", "Test", "Body")
    # print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
