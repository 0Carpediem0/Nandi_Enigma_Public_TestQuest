"""
Сервис работы с почтой через IMAP (чтение) и SMTP (отправка).
По умолчанию: yegor.starkov.06@mail.ru (Mail.ru).
Учётные данные и серверы задаются через переменные окружения или .env.
"""

import os
import imaplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email import policy
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from typing import Optional

# Почта по умолчанию (Mail.ru)
DEFAULT_STUB_EMAIL = "yegor.starkov.06@mail.ru"


def _get_config() -> dict:
    """Читает конфиг из окружения (Docker/локально)."""
    return {
        "email": os.getenv("EMAIL_USER", DEFAULT_STUB_EMAIL),
        "password": os.getenv("EMAIL_PASSWORD", ""),
        "imap_host": os.getenv("IMAP_HOST", "imap.mail.ru"),
        "imap_port": int(os.getenv("IMAP_PORT", "993")),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.mail.ru"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
    }


def fetch_recent_emails(limit: int = 10, mailbox: str = "INBOX") -> list[dict]:
    """
    Получает последние письма из почтового ящика через IMAP.
    
    :param limit: максимум писем
    :param mailbox: папка (INBOX по умолчанию)
    :return: список словарей с полями subject, from_addr, date, body_preview
    """
    cfg = _get_config()
    if not cfg["password"]:
        return [{"error": "EMAIL_PASSWORD not set", "stub": cfg["email"]}]

    result = []
    try:
        with imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"]) as mail:
            mail.login(cfg["email"], cfg["password"])
            mail.select(mailbox)
            status, data = mail.search(None, "ALL")
            if status != "OK":
                return [{"error": "IMAP search failed"}]
            ids = data[0].split()
            for email_id in reversed(ids[-limit:] if len(ids) >= limit else ids):
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                raw = msg_data[0][1]
                msg = BytesParser(policy=policy.default).parsebytes(raw)
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = (part.get_payload(decode=True) or b"").decode(errors="replace")
                            break
                else:
                    body = (msg.get_payload(decode=True) or b"").decode(errors="replace")
                result.append({
                    "subject": msg.get("Subject", ""),
                    "from_addr": msg.get("From", ""),
                    "to_addr": msg.get("To", ""),
                    "date": msg.get("Date", ""),
                    "body_preview": (body or "")[:500],
                })
    except Exception as e:
        return [{"error": str(e), "stub": cfg["email"]}]
    return result


def send_email(to_addr: str, subject: str, body: str, body_html: Optional[str] = None) -> dict:
    """
    Отправляет письмо через SMTP. Пробует порт 465 (SSL), затем 587 (STARTTLS).
    Для Mail.ru: если не отправляется — создай «Пароль для внешних приложений» в настройках почты.
    """
    cfg = _get_config()
    if not cfg["password"]:
        return {"ok": False, "error": "EMAIL_PASSWORD not set", "stub": cfg["email"]}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["email"]
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="mail.ru")
    msg["MIME-Version"] = "1.0"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    last_error = None

    for port, use_ssl in [(465, True), (587, False)]:
        try:
            if use_ssl:
                with smtplib.SMTP_SSL(cfg["smtp_host"], port) as smtp:
                    smtp.login(cfg["email"], cfg["password"])
                    refused = smtp.send_message(msg)
            else:
                with smtplib.SMTP(cfg["smtp_host"], port) as smtp:
                    smtp.starttls()
                    smtp.login(cfg["email"], cfg["password"])
                    refused = smtp.send_message(msg)
            if refused:
                return {"ok": False, "error": f"Сервер отклонил доставку: {refused}", "stub": cfg["email"]}
            return {"ok": True, "to": to_addr, "from": cfg["email"], "port": port}
        except Exception as e:
            last_error = e
            continue

    err_text = str(last_error) if last_error else "unknown"
    hint = ""
    if "535" in err_text or "Authentication" in err_text or "auth" in err_text.lower():
        hint = " Подсказка: Mail.ru может требовать «Пароль для внешних приложений» (Настройки → Безопасность)."
    return {"ok": False, "error": err_text + hint, "stub": cfg["email"]}


def list_mailboxes() -> list[str]:
    """Список папок (INBOX, Sent, ...). Нужно для поиска папки «Отправленные»."""
    cfg = _get_config()
    if not cfg["password"]:
        return []
    try:
        with imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"]) as mail:
            mail.login(cfg["email"], cfg["password"])
            status, data = mail.list()
            if status != "OK":
                return []
            folders = []
            for line in data or []:
                if not isinstance(line, bytes):
                    continue
                # Формат: (\\HasNoChildren) "/" "INBOX" или (\\Sent) "|" "Sent"
                parts = line.decode(errors="replace").split('"')
                if len(parts) >= 3:
                    name = parts[-2].strip()
                    if name:
                        folders.append(name)
            return folders
    except Exception:
        return []


def fetch_recent_emails_sent(limit: int = 10) -> list[dict]:
    """
    Последние письма из папки «Отправленные». Пробует варианты имени папки (в т.ч. Mail.ru UTF-7).
    """
    # Mail.ru «Отправленные» в IMAP — &BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-
    for folder in (
        "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-",  # Mail.ru Отправленные
        "Sent",
        "Sent Items",
        "Отправленные",
        "[Mail.ru]/Sent",
        "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0-",
    ):
        emails = fetch_recent_emails(limit=limit, mailbox=folder)
        if len(emails) == 1 and "error" in emails[0]:
            continue
        return emails
    return [{"error": "Папка «Отправленные» не найдена. Доступные: " + ", ".join(list_mailboxes())}]


def check_connection() -> dict:
    """Проверка подключения к IMAP (для здоровья сервиса в Docker)."""
    cfg = _get_config()
    out = {"imap": None, "smtp": None, "email_stub": cfg["email"]}
    if not cfg["password"]:
        out["imap"] = "no password"
        out["smtp"] = "no password"
        return out
    try:
        with imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"]) as mail:
            mail.login(cfg["email"], cfg["password"])
        out["imap"] = "ok"
    except Exception as e:
        out["imap"] = str(e)
    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as smtp:
            smtp.starttls()
            smtp.login(cfg["email"], cfg["password"])
        out["smtp"] = "ok"
    except Exception as e:
        out["smtp"] = str(e)
    return out
