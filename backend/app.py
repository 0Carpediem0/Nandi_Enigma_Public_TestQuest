"""
API для AI-агента: отправка писем, чтение входящих и отправленных.
Запуск: uvicorn app:app --host 0.0.0.0 --port 8000
"""

import os
from pathlib import Path

# Подгрузка .env до импорта email_service
_env_dir = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(_env_dir / ".env")
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from email_service import (
    send_email,
    fetch_recent_emails,
    fetch_recent_emails_sent,
    check_connection,
)

app = FastAPI(
    title="Email API для AI-агента",
    description="Отправка и чтение почты (IMAP/SMTP). Вызовы для агента.",
    version="1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Модели для агента ---

class SendEmailRequest(BaseModel):
    to: str = Field(..., description="Адрес получателя")
    subject: str = Field(..., description="Тема письма")
    body: str = Field(..., description="Текст письма")
    body_html: str | None = Field(None, description="HTML-версия (опционально)")


class SendEmailResponse(BaseModel):
    ok: bool
    to: str | None = None
    error: str | None = None


# --- Эндпоинты для AI-агента ---

@app.get("/health")
def health():
    """Проверка работы сервиса и подключения к почте."""
    return check_connection()


@app.post("/send", response_model=SendEmailResponse)
def api_send_email(req: SendEmailRequest):
    """Отправить письмо. Вызывать из AI-агента для отправки на указанный адрес."""
    result = send_email(req.to, req.subject, req.body, req.body_html)
    if result.get("ok"):
        return SendEmailResponse(ok=True, to=result.get("to"))
    raise HTTPException(status_code=400, detail=result.get("error", "Send failed"))


@app.get("/emails")
def api_emails_inbox(limit: int = 10, mailbox: str = "INBOX"):
    """Список писем во входящих (или в указанной папке). Для агента — чтение почты."""
    emails = fetch_recent_emails(limit=limit, mailbox=mailbox)
    return {"emails": emails, "count": len(emails)}


@app.get("/emails/sent")
def api_emails_sent(limit: int = 10):
    """Список отправленных писем."""
    emails = fetch_recent_emails_sent(limit=limit)
    return {"emails": emails, "count": len(emails)}


# --- Точка входа для uvicorn ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
