from datetime import datetime
from email.utils import parseaddr
from typing import Any

from psycopg.rows import dict_row

from db import get_connection


def _ticket_to_front(ticket: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ticket["id"],
        "date": ticket["created_at"],
        "full_name": ticket.get("client_name") or "Неизвестный клиент",
        "object": ticket.get("location_object") or "-",
        "phone": ticket.get("phone") or "-",
        "email": ticket["client_email"],
        "serial_numbers": ticket.get("serial_numbers") or "-",
        "device_type": ticket.get("device_type") or "-",
        "emotional_tone": ticket.get("ai_tone") or "Нейтральный",
        "question": ticket.get("question") or "-",
        "ai_response": ticket.get("ai_suggested_answer") or ticket.get("answer") or "-",
        "subject": ticket.get("subject") or "",
        "status": ticket.get("status") or "new",
        "needs_attention": bool(ticket.get("needs_attention")),
        "is_resolved": bool(ticket.get("is_resolved")),
        "category": ticket.get("ai_category"),
        "priority": ticket.get("ai_priority"),
        "ai_confidence": ticket.get("ai_confidence"),
    }


def list_tickets(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT *
        FROM tickets
        WHERE (%s::text IS NULL OR status = %s)
        ORDER BY created_at DESC
        LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (status, status, limit))
            rows = cur.fetchall()
    return [_ticket_to_front(row) for row in rows]


def get_ticket(ticket_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,))
            row = cur.fetchone()
    if not row:
        return None
    payload = _ticket_to_front(row)
    payload["answer"] = row.get("answer") or ""
    payload["ai_draft"] = row.get("ai_suggested_answer") or ""
    return payload


def update_ticket(ticket_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    if not updates:
        return get_ticket(ticket_id)

    allowed = {
        "client_name",
        "phone",
        "location_object",
        "serial_numbers",
        "device_type",
        "question",
        "answer",
        "status",
        "needs_attention",
        "is_resolved",
    }
    safe_updates = {k: v for k, v in updates.items() if k in allowed}
    if not safe_updates:
        return get_ticket(ticket_id)

    assignments = ", ".join(f"{k} = %s" for k in safe_updates.keys())
    params = list(safe_updates.values())
    params.extend([datetime.utcnow(), ticket_id])

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE tickets SET {assignments}, updated_at = %s WHERE id = %s",
                params,
            )
    return get_ticket(ticket_id)


def create_or_update_ticket_from_email(email_item: dict[str, Any]) -> tuple[int, bool]:
    from_name, from_email = parseaddr(email_item.get("from_addr") or "")
    from_email = from_email or (email_item.get("from_addr") or "unknown@example.com")
    subject = email_item.get("subject") or "(без темы)"
    message_id = (email_item.get("message_id") or "").strip() or None
    in_reply_to = (email_item.get("in_reply_to") or "").strip() or None
    body = email_item.get("body") or email_item.get("body_preview") or ""

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if message_id:
                cur.execute("SELECT id FROM tickets WHERE message_id = %s", (message_id,))
                existing = cur.fetchone()
                if existing:
                    return int(existing["id"]), False

            cur.execute(
                """
                INSERT INTO tickets (
                    client_email, client_name, subject, question, status, message_id, in_reply_to
                ) VALUES (%s, %s, %s, %s, 'new', %s, %s)
                RETURNING id
                """,
                (from_email, from_name or None, subject, body, message_id, in_reply_to),
            )
            ticket = cur.fetchone()
    return int(ticket["id"]), True


def set_ai_result(ticket_id: int, ai_result: dict[str, Any]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tickets
                SET ai_suggested_answer = %s,
                    ai_category = %s,
                    ai_priority = %s,
                    ai_tone = %s,
                    ai_confidence = %s,
                    needs_attention = %s,
                    status = 'drafted',
                    processed_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    ai_result.get("draft_answer"),
                    ai_result.get("category"),
                    ai_result.get("priority"),
                    ai_result.get("tone"),
                    ai_result.get("confidence"),
                    ai_result.get("needs_attention", False),
                    datetime.utcnow(),
                    datetime.utcnow(),
                    ticket_id,
                ),
            )


def mark_ticket_sent(ticket_id: int, final_answer: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tickets
                SET answer = %s,
                    status = 'sent',
                    is_resolved = TRUE,
                    resolved_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (final_answer, datetime.utcnow(), datetime.utcnow(), ticket_id),
            )


def search_knowledge_base(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Поиск по базе знаний: по тексту вопроса клиента возвращает топ-N релевантных записей.
    Использует полнотекстовый поиск (search_vector) и ts_rank; при отсутствии search_vector — ILIKE.
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(limit, 20))
    pattern = f"%{query.replace('%', '\\%').replace('_', '\\_')}%"

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    """
                    SELECT
                        id, title, content, short_answer, category,
                        ts_rank(search_vector, plainto_tsquery('simple', %s)) AS rank
                    FROM knowledge_base
                    WHERE is_active = TRUE
                      AND search_vector @@ plainto_tsquery('simple', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                    """,
                    (query, query, limit),
                )
            except Exception:
                # Колонка search_vector отсутствует (таблица создана через backend/db.py) — fallback на ILIKE
                cur.execute(
                    """
                    SELECT id, title, content, short_answer, category, 1.0 AS rank
                    FROM knowledge_base
                    WHERE is_active = TRUE
                      AND (title ILIKE %s OR content ILIKE %s)
                    LIMIT %s
                    """,
                    (pattern, pattern, limit),
                )
            rows = cur.fetchall()

    return [
        {
            "id": r["id"],
            "title": r["title"],
            "content": r["content"],
            "short_answer": r.get("short_answer"),
            "category": r.get("category"),
            "rank": float(r["rank"]) if r.get("rank") is not None else None,
        }
        for r in rows
    ]


def create_kb_entry(
    ticket_id: int,
    title: str,
    content: str,
    short_answer: str | None,
    category: str | None,
    tags: list[str] | None = None,
) -> int:
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_base (ticket_id, title, content, short_answer, category, tags)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ticket_id, title, content, short_answer, category, tags or []),
            )
            row = cur.fetchone()

            cur.execute(
                "UPDATE tickets SET status = 'saved_to_kb', updated_at = %s WHERE id = %s",
                (datetime.utcnow(), ticket_id),
            )
    return int(row["id"])


def create_email_log(
    ticket_id: int,
    raw_from: str,
    raw_to: str,
    raw_subject: str,
    raw_body: str,
    message_id: str | None,
    in_reply_to: str | None,
    direction: str,
    send_status: str | None = None,
    error_text: str | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO email_log (
                    ticket_id, raw_from, raw_to, raw_subject, raw_body,
                    message_id, in_reply_to, direction, send_status, error_text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ticket_id,
                    raw_from,
                    raw_to,
                    raw_subject,
                    raw_body,
                    message_id,
                    in_reply_to,
                    direction,
                    send_status,
                    error_text,
                ),
            )
