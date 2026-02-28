"""
API для AI-агента: отправка писем, чтение входящих, работа с тикетами и БД.
Запуск: uvicorn app:app --host 0.0.0.0 --port 8000
"""

import csv
import io
import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from ai_config import AIConfig
from ai_embedding import text_to_vector_384
from ai_pipeline import run_ai_pipeline
from db import init_db
from email_service import check_connection, fetch_recent_emails, fetch_recent_emails_sent, send_email
from repositories import (
    create_email_log,
    create_kb_entry,
    create_or_update_ticket_from_email,
    get_ticket,
    list_tickets,
    log_ai_run,
    mark_ticket_sent,
    set_ai_result,
    update_ticket,
)
from schemas import (
    ProcessBatchEmailsRequest,
    ProcessBatchEmailsResponse,
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


def _extract_keywords(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", text.lower())
    deduped = []
    seen = set()
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        deduped.append(word)
        if len(deduped) >= limit:
            break
    return deduped


def _process_email_to_ticket(email_item: dict) -> tuple[int, dict]:
    ticket_id = _ingest_single_email(email_item)
    ai_result = run_ai_pipeline(email_item)
    set_ai_result(ticket_id, ai_result)
    log_ai_run(
        ticket_id=ticket_id,
        payload={
            "pipeline_version": ai_result.get("pipeline_version"),
            "analyzer_model": ai_result.get("analyzer_model"),
            "generator_model": ai_result.get("generator_model"),
            "retriever_top_k": len(ai_result.get("sources", [])),
            "total_latency_ms": ai_result.get("timings_ms", {}).get("total_ms"),
            "analyzer_latency_ms": ai_result.get("timings_ms", {}).get("analyzer_ms"),
            "retrieval_latency_ms": ai_result.get("timings_ms", {}).get("retrieval_ms"),
            "generator_latency_ms": ai_result.get("timings_ms", {}).get("generator_ms"),
            "guardrails_latency_ms": ai_result.get("timings_ms", {}).get("guardrails_ms"),
            "fallback_used": ai_result.get("fallback_used", False),
            "success": True,
            "error_text": None,
        },
    )
    return ticket_id, ai_result


# --- Health and email endpoints ---
@app.get("/health")
def health():
    checks = check_connection()
    checks["db"] = "ok"
    checks["pipeline"] = {
        "version": AIConfig.PIPELINE_VERSION,
        "bert_enabled": AIConfig.BERT_ENABLED,
        "rag_enabled": AIConfig.RAG_ENABLED,
        "qwen_enabled": AIConfig.QWEN_ENABLED,
        "auto_send_enabled": AIConfig.AUTO_SEND_ENABLED,
    }
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


@app.post("/tickets/{ticket_id}/save-to-kb")
def api_save_ticket_to_kb(ticket_id: int, req: SaveToKbRequest):
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    title = req.title or f"Кейс #{ticket_id}: {ticket.get('subject') or 'без темы'}"
    content = req.content or f"Вопрос: {ticket.get('question')}\n\nОтвет: {ticket.get('answer') or ticket.get('ai_response')}"
    keywords = _extract_keywords(f"{title} {content}")
    embedding = text_to_vector_384(f"{title}\n{content}")
    kb_id = create_kb_entry(
        ticket_id=ticket_id,
        title=title,
        content=content,
        short_answer=req.short_answer or ticket.get("answer") or ticket.get("ai_response"),
        category=req.category or ticket.get("category"),
        tags=req.tags or [],
        keywords=keywords,
        embedding=embedding,
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
    ticket_id, ai_result = _process_email_to_ticket(latest_email)

    operator_subject = f"[MVP][AI] {ai_result['subject']}"
    operator_body = (
        f"Ticket ID: {ticket_id}\n"
        "MVP-обработка входящего письма\n\n"
        f"От: {ai_result['from_addr']}\n"
        f"Тема: {ai_result['subject']}\n"
        f"Категория: {ai_result['category']}\n"
        f"Приоритет: {ai_result['priority']}\n"
        f"Уверенность: {ai_result['confidence']}\n"
        f"Требуется внимание оператора: {ai_result['needs_attention']}\n"
        f"Автоотправка разрешена: {ai_result['auto_send_allowed']}\n"
        f"Причина автоотправки: {ai_result.get('auto_send_reason') or '-'}\n\n"
        "Краткое содержимое письма:\n"
        f"{ai_result['body_preview']}\n\n"
        "Черновик ответа от AI:\n"
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
        ai_confidence=ai_result.get("confidence"),
        ai_category=ai_result.get("category"),
        ai_priority=ai_result.get("priority"),
        needs_attention=bool(ai_result.get("needs_attention")),
        auto_send_allowed=bool(ai_result.get("auto_send_allowed")),
        auto_send_reason=ai_result.get("auto_send_reason"),
        ai_sources=ai_result.get("sources", []),
        pipeline_version=ai_result.get("pipeline_version"),
        timings_ms=ai_result.get("timings_ms", {}),
        sent_via_port=send_result.get("port"),
    )


@app.post("/mvp/process-batch", response_model=ProcessBatchEmailsResponse)
def api_mvp_process_batch(req: ProcessBatchEmailsRequest):
    operator_email = req.operator_email or os.getenv("OPERATOR_EMAIL")
    if req.notify_operator and not operator_email:
        raise HTTPException(
            status_code=400,
            detail="Operator email is not set. Pass operator_email in request or set OPERATOR_EMAIL in env.",
        )

    emails = fetch_recent_emails(limit=req.limit, mailbox=req.mailbox)
    if not emails:
        return ProcessBatchEmailsResponse(ok=True, processed_count=0, ticket_ids=[])
    if len(emails) == 1 and "error" in emails[0]:
        raise HTTPException(status_code=400, detail=f"IMAP error: {emails[0]['error']}")

    processed_ticket_ids = []
    failures = []
    for email_item in emails:
        try:
            ticket_id, _ = _process_email_to_ticket(email_item)
            processed_ticket_ids.append(ticket_id)
        except Exception as exc:
            failures.append(str(exc))

    digest_sent = False
    if req.notify_operator and operator_email:
        digest_subject = f"[MVP][AI-BATCH] processed={len(processed_ticket_ids)} failed={len(failures)}"
        digest_body = (
            "Результат batch-обработки писем:\n"
            f"- mailbox: {req.mailbox}\n"
            f"- processed: {len(processed_ticket_ids)}\n"
            f"- failed: {len(failures)}\n"
            f"- ticket_ids: {processed_ticket_ids}\n"
        )
        send_result = send_email(operator_email, digest_subject, digest_body)
        digest_sent = bool(send_result.get("ok"))

    return ProcessBatchEmailsResponse(
        ok=True,
        processed_count=len(processed_ticket_ids),
        ticket_ids=processed_ticket_ids,
        failed_count=len(failures),
        operator_email=operator_email,
        digest_sent=digest_sent,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
