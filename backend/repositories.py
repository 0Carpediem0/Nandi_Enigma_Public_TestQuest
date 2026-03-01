import re
from datetime import datetime
from email.utils import parseaddr
from typing import Any

from psycopg.rows import dict_row

from db import get_connection

try:
    from embedding_service import get_embedding
except ImportError:
    get_embedding = None


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
        "ai_sources": ticket.get("ai_sources") or [],
        "pipeline_version": ticket.get("pipeline_version"),
        "auto_send_allowed": bool(ticket.get("auto_send_allowed")),
        "auto_send_reason": ticket.get("auto_send_reason"),
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
                    ai_model = %s,
                    ai_sources = %s,
                    ai_reasoning_short = %s,
                    pipeline_version = %s,
                    ai_processing_time_ms = %s,
                    auto_send_allowed = %s,
                    auto_send_reason = %s,
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
                    ai_result.get("model"),
                    ai_result.get("sources", []),
                    ai_result.get("reasoning_short"),
                    ai_result.get("pipeline_version"),
                    ai_result.get("processing_time_ms"),
                    ai_result.get("auto_send_allowed", False),
                    ai_result.get("auto_send_reason"),
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


def _kb_row_to_dict(r: dict) -> dict[str, Any]:
    return {
        "id": r["id"],
        "title": r["title"],
        "content": r["content"],
        "short_answer": r.get("short_answer"),
        "category": r.get("category"),
        "rank": float(r["rank"]) if r.get("rank") is not None else None,
    }


def search_knowledge_base(
    query: str,
    limit: int = 5,
    use_vector: bool = False,
) -> list[dict[str, Any]]:
    """
    Поиск по базе знаний. По умолчанию — полнотекст (russian).
    При use_vector=True и заполненных embedding — семантический поиск (pgvector).
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(limit, 20))
    pattern = f"%{query.replace('%', '\\%').replace('_', '\\_')}%"

    if use_vector and get_embedding:
        emb = get_embedding(query)
        if emb and len(emb) == 384:
            vec_str = "[" + ",".join(str(x) for x in emb) + "]"
            with get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    try:
                        cur.execute(
                            """
                            SELECT id, title, content, short_answer, category,
                                   (1 - (embedding <=> %s::vector)) AS rank
                            FROM knowledge_base
                            WHERE is_active = TRUE AND embedding IS NOT NULL
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (vec_str, vec_str, limit),
                        )
                        rows = cur.fetchall()
                        if rows:
                            return [_kb_row_to_dict(r) for r in rows]
                    except Exception:
                        pass

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    """
                    SELECT
                        id, title, content, short_answer, category,
                        ts_rank(search_vector, plainto_tsquery('russian', %s)) AS rank
                    FROM knowledge_base
                    WHERE is_active = TRUE
                      AND search_vector @@ plainto_tsquery('russian', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                    """,
                    (query, query, limit),
                )
                rows = cur.fetchall()
                if not rows:
                    raise ValueError("no rows")
            except Exception:
                rows = []
            if not rows:
                words = [
                    w
                    for w in re.split(r"\W+", query)
                    if len(w) >= 2 and not any(c in w for c in "'&!()")
                ]
                words = words[:10]
                if words:
                    # OR по каждому слову через plainto_tsquery (надёжнее, чем to_tsquery с "a | b")
                    or_ts = " | ".join(
                        "plainto_tsquery('russian', %s)" for _ in words
                    )
                    try:
                        cur.execute(
                            f"""
                            SELECT
                                id, title, content, short_answer, category,
                                1.0 AS rank
                            FROM knowledge_base
                            WHERE is_active = TRUE
                              AND search_vector @@ ({or_ts})
                            ORDER BY id
                            LIMIT %s
                            """,
                            (*words, limit),
                        )
                        rows = cur.fetchall()
                    except Exception:
                        pass
            if not rows:
                try:
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
                except Exception:
                    rows = []
            if not rows and words:
                for w in words:
                    try:
                        like_pat = f"%{w.replace('%', '\\%').replace('_', '\\_')}%"
                        cur.execute(
                            """
                            SELECT id, title, content, short_answer, category, 1.0 AS rank
                            FROM knowledge_base
                            WHERE is_active = TRUE
                              AND (title ILIKE %s OR content ILIKE %s)
                            LIMIT %s
                            """,
                            (like_pat, like_pat, limit),
                        )
                        rows = cur.fetchall()
                        if rows:
                            break
                    except Exception:
                        continue
    return [_kb_row_to_dict(r) for r in rows]


def fill_knowledge_base_embeddings() -> tuple[int, int]:
    """
    Заполняет колонку embedding для записей knowledge_base, где embedding IS NULL.
    Использует HF Inference API (feature-extraction). Возвращает (обновлено, ошибок).
    """
    if not get_embedding:
        return 0, 0
    updated = 0
    errors = 0
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'knowledge_base'"
                )
                if "embedding" not in {r[0] for r in cur.fetchall()}:
                    return 0, 0
            except Exception:
                return 0, 0
            cur.execute(
                "SELECT id, title, content FROM knowledge_base WHERE embedding IS NULL"
            )
            rows = cur.fetchall()
    for r in rows:
        text = f"{r.get('title') or ''} {r.get('content') or ''}".strip()[:8192]
        if not text:
            continue
        emb = get_embedding(text)
        if not emb or len(emb) != 384:
            errors += 1
            continue
        vec_str = "[" + ",".join(str(x) for x in emb) + "]"
        with get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "UPDATE knowledge_base SET embedding = %s::vector, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (vec_str, r["id"]),
                    )
                    updated += 1
                except Exception:
                    errors += 1
    return updated, errors


def create_kb_entry(
    ticket_id: int,
    title: str,
    content: str,
    short_answer: str | None,
    category: str | None,
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    embedding: list[float] | None = None,
) -> int:
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_base (ticket_id, title, content, short_answer, category, tags, keywords, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ticket_id, title, content, short_answer, category, tags or [], keywords or [], embedding),
            )
            row = cur.fetchone()

            cur.execute(
                "UPDATE tickets SET status = 'saved_to_kb', updated_at = %s WHERE id = %s",
                (datetime.utcnow(), ticket_id),
            )
    return int(row["id"])


def incoming_email_already_processed(message_id: str | None) -> bool:
    """Проверяет, обрабатывали ли мы уже входящее письмо с этим message_id (есть запись в email_log)."""
    if not (message_id and str(message_id).strip()):
        return False
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM email_log WHERE message_id = %s AND direction = 'incoming' LIMIT 1",
                (message_id.strip(),),
            )
            return cur.fetchone() is not None


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


def search_kb_hybrid(
    query_text: str,
    category: str | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    like_q = f"%{query_text.strip()}%"
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    """
                    SELECT id, title, content, short_answer, category, tags, usage_count, success_rate
                    FROM knowledge_base
                    WHERE is_active = TRUE
                      AND (%s::text IS NULL OR category = %s)
                      AND (
                            title ILIKE %s
                         OR content ILIKE %s
                         OR search_vector @@ plainto_tsquery('simple', %s)
                      )
                    ORDER BY usage_count DESC, success_rate DESC, created_at DESC
                    LIMIT %s
                    """,
                    (category, category, like_q, like_q, query_text, top_k),
                )
                return cur.fetchall()
            except Exception:
                # Fallback for instances where search_vector is not present yet.
                cur.execute(
                    """
                    SELECT id, title, content, short_answer, category, tags, usage_count, success_rate
                    FROM knowledge_base
                    WHERE is_active = TRUE
                      AND (%s::text IS NULL OR category = %s)
                      AND (title ILIKE %s OR content ILIKE %s)
                    ORDER BY usage_count DESC, success_rate DESC, created_at DESC
                    LIMIT %s
                    """,
                    (category, category, like_q, like_q, top_k),
                )
                return cur.fetchall()


def log_ai_run(ticket_id: int, payload: dict[str, Any]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_run_log (
                    ticket_id, pipeline_version, analyzer_model, generator_model, retriever_top_k,
                    total_latency_ms, analyzer_latency_ms, retrieval_latency_ms,
                    generator_latency_ms, guardrails_latency_ms, fallback_used, success, error_text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ticket_id,
                    payload.get("pipeline_version") or "v1",
                    payload.get("analyzer_model"),
                    payload.get("generator_model"),
                    payload.get("retriever_top_k"),
                    payload.get("total_latency_ms"),
                    payload.get("analyzer_latency_ms"),
                    payload.get("retrieval_latency_ms"),
                    payload.get("generator_latency_ms"),
                    payload.get("guardrails_latency_ms"),
                    payload.get("fallback_used", False),
                    payload.get("success", True),
                    payload.get("error_text"),
                ),
            )
