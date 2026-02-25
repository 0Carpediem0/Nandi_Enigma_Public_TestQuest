"""
Простой CLI: посмотреть входящие и отправить письмо конкретному адресу.
Запуск:
  python cli.py list          — показать последние письма (где они лежат)
  python cli.py send <адрес> "Тема" "Текст письма"
"""
import sys
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from email_service import fetch_recent_emails, send_email


def main():
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python cli.py list [папка] [сколько]   — показать письма (папка по умолч. INBOX, кол-во 10)")
        print('  python cli.py send "email@example.com" "Тема" "Текст письма"')
        return

    cmd = sys.argv[1].lower()

    if cmd == "list":
        mailbox = sys.argv[2] if len(sys.argv) > 2 else "INBOX"
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        emails = fetch_recent_emails(limit=limit, mailbox=mailbox)
        print(json.dumps(emails, indent=2, ensure_ascii=False))

    elif cmd == "send":
        if len(sys.argv) < 5:
            print('Нужно: python cli.py send "кому@example.com" "Тема" "Текст письма"')
            return
        to_addr = sys.argv[2]
        subject = sys.argv[3]
        body = " ".join(sys.argv[4:])  # текст может быть из нескольких слов
        result = send_email(to_addr, subject, body)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print("Команда должна быть: list или send")


if __name__ == "__main__":
    main()
