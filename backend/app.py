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


class ProcessLatestEmailRequest(BaseModel):
    mailbox: str = Field("INBOX", description="Папка, из которой берём последнее письмо")
    operator_email: str | None = Field(
        None,
        description="Почта оператора. Если не передана, используется OPERATOR_EMAIL из окружения.",
    )


class ProcessLatestEmailResponse(BaseModel):
    ok: bool
    source_from: str
    source_subject: str
    operator_email: str
    ai_decision: str
    ai_draft_response: str
    sent_via_port: int | None = None
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


def _run_ai_stub(email_item: dict) -> dict:
    """
    Прототип AI-обработки: классифицирует обращение по ключевым словам
    и генерирует черновик ответа оператору.
    """
    subject = str(email_item.get("subject", "")).strip()
    from_addr = str(email_item.get("from_addr", "")).strip()
    body_preview = str(email_item.get("body_preview", "")).strip()
    text = f"{subject} {body_preview}".lower()

    if any(word in text for word in ("не работает", "ошибка", "авар", "срочно", "слом")):
        priority = "Высокий"
        category = "Инцидент / Неисправность"
    elif any(word in text for word in ("как", "инструкция", "подключ", "настрой")):
        priority = "Средний"
        category = "Консультация / Настройка"
    else:
        priority = "Низкий"
        category = "Общий запрос"

    ai_draft_response = (
        "Здравствуйте! Получили ваше обращение и передали его в работу оператору. "
        "Пожалуйста, при необходимости уточните модель устройства и серийный номер. "
        "Мы вернёмся с подробным ответом в ближайшее время."
    )

    return {
        "from_addr": from_addr or "unknown",
        "subject": subject or "(без темы)",
        "body_preview": body_preview or "(пустое письмо)",
        "priority": priority,
        "category": category,
        "ai_draft_response": ai_draft_response,
    }


@app.post("/mvp/process-latest", response_model=ProcessLatestEmailResponse)
def api_mvp_process_latest(req: ProcessLatestEmailRequest):
    """
    MVP-конвейер:
    1) Берёт последнее письмо из IMAP.
    2) Прогоняет через AI-заглушку.
    3) Отправляет оператору письмо с результатом обработки.
    """
    operator_email = req.operator_email or os.getenv("OPERATOR_EMAIL")
    if not operator_email:
        raise HTTPException(
            status_code=400,
            detail="Operator email is not set. Pass operator_email in request or set OPERATOR_EMAIL in env.",
        )

    emails = fetch_recent_emails(limit=1, mailbox=req.mailbox)
    if not emails:
        raise HTTPException(status_code=404, detail="No emails found in selected mailbox.")
    if len(emails) == 1 and "error" in emails[0]:
        raise HTTPException(status_code=400, detail=f"IMAP error: {emails[0]['error']}")

    latest_email = emails[0]
    ai_result = _run_ai_stub(latest_email)

    operator_subject = f"[MVP][AI-STUB] {ai_result['subject']}"
    operator_body = (
        "MVP-обработка входящего письма\n\n"
        f"От: {ai_result['from_addr']}\n"
        f"Тема: {ai_result['subject']}\n"
        f"Категория (stub): {ai_result['category']}\n"
        f"Приоритет (stub): {ai_result['priority']}\n\n"
        "Краткое содержимое письма:\n"
        f"{ai_result['body_preview']}\n\n"
        "Черновик ответа от AI-заглушки:\n"
        f"{ai_result['ai_draft_response']}\n"
    )

    send_result = send_email(operator_email, operator_subject, operator_body)
    if not send_result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=f"SMTP error: {send_result.get('error', 'unknown send error')}",
        )

    return ProcessLatestEmailResponse(
        ok=True,
        source_from=ai_result["from_addr"],
        source_subject=ai_result["subject"],
        operator_email=operator_email,
        ai_decision=f"{ai_result['category']} / {ai_result['priority']}",
        ai_draft_response=ai_result["ai_draft_response"],
        sent_via_port=send_result.get("port"),
    )


# --- Точка входа для uvicorn ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
