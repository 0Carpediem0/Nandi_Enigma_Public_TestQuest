"""
API для AI-агента: отправка писем, чтение входящих, работа с тикетами и БД.
Запуск: uvicorn app:app --host 0.0.0.0 --port 8000
"""

import csv
import io
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from email_service import check_connection, fetch_recent_emails, fetch_recent_emails_sent, send_email
from repositories import (
    create_email_log,
    create_kb_entry,
    create_or_update_ticket_from_email,
    fill_knowledge_base_embeddings,
    get_ticket,
    list_tickets,
    mark_ticket_sent,
    search_knowledge_base,
    set_ai_result,
    update_ticket,
)
from qwen_service import ask_qwen
from schemas import (
    KnowledgeBaseEntry,
    KnowledgeBaseSearchResponse,
    KbAskRequest,
    KbAskResponse,
    ProcessLatestEmailRequest,
    ProcessLatestEmailResponse,
    ReplyTicketRequest,
    SaveToKbRequest,
    SendEmailRequest,
    SendEmailResponse,
    UpdateTicketRequest,
)

# Подгрузка .env до импорта зависимостей от окружения
_env_dir = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(_env_dir / ".env")
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("support_api")

app = FastAPI(
    title="Email + Tickets API для AI-агента",
    description="Отправка и чтение почты (IMAP/SMTP), тикеты и база знаний.",
    version="2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    logger.info("Initializing database schema")
    init_db()
    logger.info("Database schema initialized")


def _get_draft_from_kb_qwen(question: str, limit: int = 5) -> str:
    """
    Черновик ответа по базе знаний + Qwen (та же логика, что в /kb/ask).
    Если по запросу ничего не найдено или Qwen недоступен — возвращает fallback-текст.
    """
    question = (question or "").strip()
    if not question:
        return (
            "Здравствуйте! Получили ваше обращение. Обратитесь к оператору для уточнения запроса."
        )
    entries = search_knowledge_base(query=question, limit=limit, use_vector=False)
    if not entries:
        return (
            "Здравствуйте! По вашему запросу в базе знаний ничего не найдено. "
            "Ответьте на это письмо или обратитесь к оператору."
        )
    system_prompt = (
        "Ты — помощник техподдержки. Отвечай только на основе приведённой ниже информации из базы знаний. "
        "Отвечай кратко, по существу, на русском языке. Не придумывай факты.\n\n"
        + _build_kb_context(entries)
    )
    answer = ask_qwen(system_prompt, question)
    if answer:
        return answer
    first = entries[0]
    fallback = first.get("short_answer") or (first.get("content") or "")[:500]
    if fallback:
        return fallback.strip()
    return (
        "Здравствуйте! Ответ по вашему запросу временно недоступен. Обратитесь к оператору."
    )


def _run_ai_stub(email_item: dict) -> dict:
    subject = str(email_item.get("subject", "")).strip()
    from_addr = str(email_item.get("from_addr", "")).strip()
    body_preview = str(email_item.get("body_preview", "")).strip()
    text = f"{subject} {body_preview}".lower()

    if any(word in text for word in ("не работает", "ошибка", "авар", "срочно", "слом")):
        priority = "Высокий"
        category = "Инцидент / Неисправность"
        confidence = 0.84
        tone = "Негативный"
        needs_attention = True
    elif any(word in text for word in ("как", "инструкция", "подключ", "настрой")):
        priority = "Средний"
        category = "Консультация / Настройка"
        confidence = 0.78
        tone = "Нейтральный"
        needs_attention = False
    else:
        priority = "Низкий"
        category = "Общий запрос"
        confidence = 0.66
        tone = "Нейтральный"
        needs_attention = False

    # Черновик ответа из базы знаний + Qwen (вопрос = тема + текст письма)
    question_for_kb = f"{subject} {body_preview}".strip()[:2000]
    draft_answer = _get_draft_from_kb_qwen(question_for_kb, limit=5)

    return {
        "from_addr": from_addr or "unknown",
        "subject": subject or "(без темы)",
        "body_preview": body_preview or "(пустое письмо)",
        "priority": priority,
        "category": category,
        "tone": tone,
        "confidence": confidence,
        "needs_attention": needs_attention,
        "draft_answer": draft_answer,
    }


def _ingest_single_email(email_item: dict) -> int:
    ticket_id, created = create_or_update_ticket_from_email(email_item)
    create_email_log(
        ticket_id=ticket_id,
        raw_from=str(email_item.get("from_addr") or ""),
        raw_to=str(email_item.get("to_addr") or ""),
        raw_subject=str(email_item.get("subject") or ""),
        raw_body=str(email_item.get("body") or email_item.get("body_preview") or ""),
        message_id=(email_item.get("message_id") or None),
        in_reply_to=(email_item.get("in_reply_to") or None),
        direction="incoming",
    )
    logger.info("Email ingested into ticket_id=%s created=%s", ticket_id, created)
    return ticket_id


# --- Health and email endpoints ---
@app.get("/health")
def health():
    checks = check_connection()
    checks["db"] = "ok"
    return checks


@app.post("/send", response_model=SendEmailResponse)
def api_send_email(req: SendEmailRequest):
    result = send_email(req.to, req.subject, req.body, req.body_html)
    if result.get("ok"):
        return SendEmailResponse(ok=True, to=result.get("to"))
    raise HTTPException(status_code=400, detail=result.get("error", "Send failed"))


@app.get("/emails")
def api_emails_inbox(limit: int = 10, mailbox: str = "INBOX"):
    emails = fetch_recent_emails(limit=limit, mailbox=mailbox)
    return {"emails": emails, "count": len(emails)}


@app.get("/emails/sent")
def api_emails_sent(limit: int = 10):
    emails = fetch_recent_emails_sent(limit=limit)
    return {"emails": emails, "count": len(emails)}


@app.post("/emails/ingest")
def api_ingest_emails(limit: int = 10, mailbox: str = "INBOX"):
    emails = fetch_recent_emails(limit=limit, mailbox=mailbox)
    if len(emails) == 1 and "error" in emails[0]:
        raise HTTPException(status_code=400, detail=f"IMAP error: {emails[0]['error']}")

    ingested = []
    for item in emails:
        ticket_id = _ingest_single_email(item)
        ingested.append(ticket_id)
    return {"ok": True, "ingested_count": len(ingested), "ticket_ids": ingested}


# --- Tickets API for frontend ---
@app.get("/tickets")
def api_list_tickets(limit: int = 100, status: str | None = None):
    return list_tickets(limit=limit, status=status)


@app.get("/tickets/{ticket_id}")
def api_get_ticket(ticket_id: int):
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.patch("/tickets/{ticket_id}")
def api_update_ticket(ticket_id: int, req: UpdateTicketRequest):
    updated = update_ticket(ticket_id, req.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return updated


@app.post("/tickets/{ticket_id}/reply")
def api_reply_ticket(ticket_id: int, req: ReplyTicketRequest):
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    to_email = req.to_email or ticket["email"]
    subject = req.subject or f"Re: {ticket.get('subject') or 'Ваше обращение'}"
    result = send_email(to_email, subject, req.body)

    create_email_log(
        ticket_id=ticket_id,
        raw_from=os.getenv("EMAIL_USER", ""),
        raw_to=to_email,
        raw_subject=subject,
        raw_body=req.body,
        message_id=None,
        in_reply_to=None,
        direction="outgoing",
        send_status="ok" if result.get("ok") else "error",
        error_text=result.get("error"),
    )

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=f"SMTP error: {result.get('error', 'unknown')}")

    mark_ticket_sent(ticket_id, req.body)
    logger.info("Ticket %s replied to %s", ticket_id, to_email)
    return {"ok": True, "ticket_id": ticket_id, "to": to_email, "port": result.get("port")}


# --- База знаний (поиск для Qwen и клиентов) ---
@app.get("/kb/search", response_model=KnowledgeBaseSearchResponse)
def api_kb_search(q: str = "", limit: int = 5, use_vector: bool = False):
    """
    Поиск по базе знаний. use_vector=true — семантический поиск (нужны заполненные embedding).
    """
    entries = search_knowledge_base(query=q, limit=limit, use_vector=use_vector)
    return KnowledgeBaseSearchResponse(
        query=q,
        count=len(entries),
        entries=[KnowledgeBaseEntry(**e) for e in entries],
    )


@app.post("/kb/refresh-embeddings")
def api_kb_refresh_embeddings():
    """
    Заполняет колонку embedding для всех записей knowledge_base, где она NULL.
    Требуются HF_TOKEN и EMBEDDING_MODEL в .env. Долго при большом объёме.
    """
    updated, errors = fill_knowledge_base_embeddings()
    return {"ok": True, "updated": updated, "errors": errors}


def _build_kb_context(entries: list[dict]) -> str:
    """Собирает контекст из записей БЗ для системного промпта Qwen."""
    if not entries:
        return "В базе знаний нет релевантных записей."
    parts = []
    for e in entries:
        title = e.get("title") or "Без названия"
        content = (e.get("content") or "").strip()
        parts.append(f"--- Тема: {title} ---\n{content}")
    return "\n\n".join(parts)


@app.post("/kb/ask", response_model=KbAskResponse)
def api_kb_ask(req: KbAskRequest):
    """
    Вопрос клиента → поиск в базе знаний → контекст в Qwen → ответ.
    Если Qwen отключён или недоступен, возвращается short_answer первой подходящей записи (fallback=True).
    """
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question не может быть пустым")

    entries = search_knowledge_base(query=question, limit=req.limit, use_vector=req.use_vector)
    source_ids = [e["id"] for e in entries]

    if not entries:
        return KbAskResponse(
            question=question,
            answer="По вашему запросу в базе знаний ничего не найдено. Обратитесь к оператору.",
            source_ids=[],
            fallback=True,
        )

    system_prompt = (
        "Ты — помощник техподдержки. Отвечай только на основе приведённой ниже информации из базы знаний. "
        "Отвечай кратко, по существу, на русском языке. Не придумывай факты.\n\n"
        + _build_kb_context(entries)
    )
    answer = ask_qwen(system_prompt, question)

    if answer:
        return KbAskResponse(
            question=question,
            answer=answer,
            source_ids=source_ids,
            fallback=False,
        )

    # Fallback: первый short_answer или начало content
    first = entries[0]
    fallback_text = first.get("short_answer") or (first.get("content") or "")[:500]
    if fallback_text:
        fallback_text = fallback_text.strip()
    if not fallback_text:
        fallback_text = "Ответ по вашему запросу временно недоступен. Обратитесь к оператору."
    logger.info("Qwen unavailable or empty response, using fallback for question=%s", question[:50])
    return KbAskResponse(
        question=question,
        answer=fallback_text,
        source_ids=source_ids,
        fallback=True,
    )


@app.post("/tickets/{ticket_id}/save-to-kb")
def api_save_ticket_to_kb(ticket_id: int, req: SaveToKbRequest):
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    title = req.title or f"Кейс #{ticket_id}: {ticket.get('subject') or 'без темы'}"
    content = req.content or f"Вопрос: {ticket.get('question')}\n\nОтвет: {ticket.get('answer') or ticket.get('ai_response')}"
    kb_id = create_kb_entry(
        ticket_id=ticket_id,
        title=title,
        content=content,
        short_answer=req.short_answer or ticket.get("answer") or ticket.get("ai_response"),
        category=req.category or ticket.get("category"),
        tags=req.tags or [],
    )
    logger.info("Ticket %s saved to KB id=%s", ticket_id, kb_id)
    return {"ok": True, "ticket_id": ticket_id, "kb_id": kb_id}


@app.get("/tickets/export")
def api_export_tickets(status: str | None = None):
    rows = list_tickets(limit=1000, status=status)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "date",
            "full_name",
            "email",
            "status",
            "emotional_tone",
            "question",
            "ai_response",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("id"),
                row.get("date"),
                row.get("full_name"),
                row.get("email"),
                row.get("status"),
                row.get("emotional_tone"),
                row.get("question"),
                row.get("ai_response"),
            ]
        )
    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tickets_export.csv"},
    )


# --- Existing MVP endpoint expanded with DB ---
@app.post("/mvp/process-latest", response_model=ProcessLatestEmailResponse)
def api_mvp_process_latest(req: ProcessLatestEmailRequest):
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
    ticket_id = _ingest_single_email(latest_email)
    ai_result = _run_ai_stub(latest_email)
    set_ai_result(ticket_id, ai_result)

    operator_subject = f"[MVP] {ai_result['subject']}"
    operator_body = (
        f"Ticket ID: {ticket_id}\n"
        "Обработка входящего письма (база знаний + Qwen)\n\n"
        f"От: {ai_result['from_addr']}\n"
        f"Тема: {ai_result['subject']}\n"
        f"Категория: {ai_result['category']}\n"
        f"Приоритет: {ai_result['priority']}\n"
        f"Уверенность: {ai_result['confidence']}\n\n"
        "Содержимое письма:\n"
        f"{ai_result['body_preview']}\n\n"
        "Черновик ответа (база знаний + Qwen):\n"
        f"{ai_result['draft_answer']}\n"
    )

    send_result = send_email(operator_email, operator_subject, operator_body)
    create_email_log(
        ticket_id=ticket_id,
        raw_from=os.getenv("EMAIL_USER", ""),
        raw_to=operator_email,
        raw_subject=operator_subject,
        raw_body=operator_body,
        message_id=None,
        in_reply_to=latest_email.get("message_id"),
        direction="outgoing",
        send_status="ok" if send_result.get("ok") else "error",
        error_text=send_result.get("error"),
    )

    if not send_result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=f"SMTP error: {send_result.get('error', 'unknown send error')}",
        )

    logger.info("MVP processed ticket_id=%s and sent to operator=%s", ticket_id, operator_email)
    return ProcessLatestEmailResponse(
        ok=True,
        source_from=ai_result["from_addr"],
        source_subject=ai_result["subject"],
        operator_email=operator_email,
        ai_decision=f"{ai_result['category']} / {ai_result['priority']}",
        ai_draft_response=ai_result["draft_answer"],
        sent_via_port=send_result.get("port"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
