"""
Пример: как через код посмотреть письма и отправить письмо с аккаунта.
Запуск из любой папки:  python example_usage.py   или   python backend/example_usage.py
"""

import os
import sys
from pathlib import Path

# Папка backend — чтобы работало при запуске из корня проекта
_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# Подгружаем .env
def _load_env():
    env_file = _backend_dir / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        load_dotenv()
    except ImportError:
        pass
    # Если пароль так и не подхватился — читаем .env вручную (обход проблем с путём/кодировкой)
    if not os.getenv("EMAIL_PASSWORD") and env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if key and value and not os.getenv(key):
                        os.environ[key] = value

_load_env()

from email_service import fetch_recent_emails, fetch_recent_emails_sent, send_email


def _check_env():
    """Проверка: есть ли пароль; если нет — подсказка про .env."""
    if os.getenv("EMAIL_PASSWORD"):
        return
    env_path = _backend_dir / ".env"
    print(
        "Пароль не задан. Создайте файл с учётными данными:\n"
        f"  1) Файл:  {env_path}\n"
        "  2) Скопируйте содержимое из .env.example и вставьте свой пароль в EMAIL_PASSWORD=...\n"
        "     Пример строки:  EMAIL_PASSWORD=ваш_пароль\n"
    )


def _print_letters(emails, title, show_to=False):
    """Печатает список писем в терминал. show_to=True — для папки «Отправленные» (показываем Кому)."""
    ok = [e for e in emails if "error" not in e]
    print(f"{title} Найдено: {len(ok)}\n")
    for i, letter in enumerate(emails, 1):
        if "error" in letter:
            print(f"  Ошибка: {letter.get('error')}")
            continue
        print(f"--- Письмо {i} ---")
        if show_to and letter.get("to_addr"):
            print(f"  Кому:  {letter.get('to_addr')}")
        else:
            print(f"  От:    {letter.get('from_addr')}")
        print(f"  Тема:  {letter.get('subject')}")
        print(f"  Дата:  {letter.get('date')}")
        print(f"  Текст: {letter.get('body_preview', '')[:200]}...")
        print()
    return emails


def view_emails():
    """Входящие (INBOX). Результат — в этом же терминале."""
    emails = fetch_recent_emails(limit=5, mailbox="INBOX")
    return _print_letters(emails, "Входящие (INBOX).")


def view_sent():
    """Отправленные письма (папка Sent) — здесь видны письма, отправленные через SMTP."""
    emails = fetch_recent_emails_sent(limit=5)
    return _print_letters(emails, "Отправленные (Sent).", show_to=True)


def send_example():
    """Отправить письмо с этого аккаунта на указанный адрес."""
    to_addr = "begor0376@gmail.com"   # замени на нужный адрес
    subject = "Тест из кода"
    body = "Привет, это письмо отправлено через наш скрипт."
    result = send_email(to_addr, subject, body)
    if result.get("ok"):
        print("Отправлено:", result.get("to"), "от", result.get("from"), "(порт", result.get("port", ""), ")")
    else:
        print("Ошибка отправки:", result.get("error"))
    return result


def send_to_self():
    """Отправка письма себе на тот же ящик (yegor.starkov.06@mail.ru). Проверка: доставляет ли Mail.ru SMTP вообще."""
    self_addr = os.getenv("EMAIL_USER", "yegor.starkov.06@mail.ru")
    result = send_email(self_addr, "Тест SMTP себе", "Если это письмо пришло во входящие — SMTP доставляет. Если нет — Mail.ru, скорее всего, не доставляет письма с программ.")
    if result.get("ok"):
        print("Отправлено себе на", self_addr, "(порт", result.get("port"), ")")
        print("  → Проверь ВХОДЯЩИЕ на", self_addr, "— пришло ли письмо.")
    else:
        print("Ошибка:", result.get("error"))
    return result


if __name__ == "__main__":
    _check_env()
    print("=== Входящие ===\n")
    view_emails()

    print("\n=== Отправленные (SMTP-письма видны здесь) ===\n")
    view_sent()

    print("\n=== Тест: отправка письма СЕБЕ (проверка доставки Mail.ru) ===\n")
    send_to_self()

    print("\n=== Отправка письма на внешний адрес ===\n")
    send_example()
