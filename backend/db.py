import logging
import os
from contextlib import contextmanager

import psycopg

logger = logging.getLogger("support_api")


def get_db_config() -> dict:
    return {
        "host": os.getenv("PGHOST", "postgres"),
        "port": int(os.getenv("PGPORT", "5432")),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", "postgres"),
        "dbname": os.getenv("PGDATABASE", "test"),
    }


@contextmanager
def get_connection():
    cfg = get_db_config()
    logger.info("DB connect: host=%s port=%s user=%s dbname=%s", cfg["host"], cfg["port"], cfg["user"], cfg["dbname"])
    conn = psycopg.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        dbname=cfg["dbname"],
        autocommit=True,
        options="-c client_encoding=UTF8",
    )
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                has_pgvector = True
            except Exception as e:
                if "vector" in str(e).lower() or "not available" in str(e).lower():
                    has_pgvector = False
                    import logging
                    logging.getLogger("support_api").warning(
                        "pgvector не установлен — расширение vector пропущено. Поиск по embedding в KB будет недоступен. Ошибка: %s", e
                    )
                else:
                    raise

    statements = [
        """
        CREATE TABLE IF NOT EXISTS operators (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            name VARCHAR(255) NOT NULL DEFAULT 'Оператор',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id SERIAL PRIMARY KEY,
            client_email VARCHAR(255) NOT NULL,
            client_name VARCHAR(255),
            phone VARCHAR(50),
            location_object VARCHAR(255),
            serial_numbers VARCHAR(255),
            device_type VARCHAR(255),
            subject VARCHAR(500),
            question TEXT,
            answer TEXT,
            status VARCHAR(50) DEFAULT 'new',
            ai_confidence FLOAT,
            ai_processing_time_ms INTEGER,
            ai_suggested_answer TEXT,
            ai_category VARCHAR(100),
            ai_priority VARCHAR(50),
            ai_tone VARCHAR(50),
            ai_model VARCHAR(100),
            ai_sources JSONB DEFAULT '[]'::jsonb,
            ai_reasoning_short TEXT,
            pipeline_version VARCHAR(50),
            auto_send_allowed BOOLEAN DEFAULT FALSE,
            auto_send_reason TEXT,
            needs_attention BOOLEAN DEFAULT FALSE,
            is_resolved BOOLEAN DEFAULT FALSE,
            message_id VARCHAR(255) UNIQUE,
            in_reply_to VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            resolved_at TIMESTAMP,
            search_vector tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('simple', coalesce(question,'')), 'A') ||
                setweight(to_tsvector('simple', coalesce(answer,'')), 'B')
            ) STORED
        );
        """,
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ai_processing_time_ms INTEGER;",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ai_model VARCHAR(100);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ai_sources JSONB DEFAULT '[]'::jsonb;",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ai_reasoning_short TEXT;",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS pipeline_version VARCHAR(50);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS auto_send_allowed BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS auto_send_reason TEXT;",
        """
        ALTER TABLE tickets
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', coalesce(question,'')), 'A') ||
            setweight(to_tsvector('simple', coalesce(answer,'')), 'B')
        ) STORED;
        """,
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS phone VARCHAR(50);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS location_object VARCHAR(255);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS serial_numbers VARCHAR(255);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS device_type VARCHAR(255);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ai_category VARCHAR(100);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ai_priority VARCHAR(50);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ai_tone VARCHAR(50);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP;",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS message_id VARCHAR(255);",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS in_reply_to VARCHAR(255);",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_message_id_unique ON tickets(message_id);",
        "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);",
        "CREATE INDEX IF NOT EXISTS idx_tickets_client_email ON tickets(client_email);",
        "CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_tickets_needs_attention ON tickets(needs_attention);",
        "CREATE INDEX IF NOT EXISTS idx_tickets_search ON tickets USING GIN (search_vector);",
        """
        CREATE TABLE IF NOT EXISTS email_log (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
            raw_from VARCHAR(255) NOT NULL,
            raw_to VARCHAR(255),
            raw_subject VARCHAR(500),
            raw_body TEXT,
            message_id VARCHAR(255),
            in_reply_to VARCHAR(255),
            direction VARCHAR(20) DEFAULT 'incoming',
            send_status VARCHAR(50),
            error_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "ALTER TABLE email_log ADD COLUMN IF NOT EXISTS send_status VARCHAR(50);",
        "ALTER TABLE email_log ADD COLUMN IF NOT EXISTS error_text TEXT;",
        "CREATE INDEX IF NOT EXISTS idx_email_log_ticket ON email_log(ticket_id);",
        "CREATE INDEX IF NOT EXISTS idx_email_log_message_id ON email_log(message_id);",
        """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
            title VARCHAR(500) NOT NULL,
            content TEXT NOT NULL,
            short_answer TEXT,
            tags TEXT[],
            category VARCHAR(100),
            usage_count INTEGER DEFAULT 0,
            success_rate FLOAT DEFAULT 1.0,
            keywords TEXT[],
            embedding vector(384),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            search_vector tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('simple', coalesce(title,'')), 'A') ||
                setweight(to_tsvector('simple', coalesce(content,'')), 'B')
            ) STORED
        );
        """,
        "ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS success_rate FLOAT DEFAULT 1.0;",
        "ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS keywords TEXT[];",
        "ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding vector(384);",
        "ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL;",
        """
        ALTER TABLE knowledge_base
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', coalesce(title,'')), 'A') ||
            setweight(to_tsvector('simple', coalesce(content,'')), 'B')
        ) STORED;
        """,
        "CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_base(category);",
        "CREATE INDEX IF NOT EXISTS idx_kb_active ON knowledge_base(is_active);",
        "CREATE INDEX IF NOT EXISTS idx_kb_search ON knowledge_base USING GIN (search_vector);",
        """
        CREATE TABLE IF NOT EXISTS ai_run_log (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
            pipeline_version VARCHAR(50) NOT NULL,
            analyzer_model VARCHAR(100),
            generator_model VARCHAR(100),
            retriever_top_k INTEGER,
            total_latency_ms INTEGER,
            analyzer_latency_ms INTEGER,
            retrieval_latency_ms INTEGER,
            generator_latency_ms INTEGER,
            guardrails_latency_ms INTEGER,
            fallback_used BOOLEAN DEFAULT FALSE,
            success BOOLEAN DEFAULT TRUE,
            error_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_ai_run_log_ticket_id ON ai_run_log(ticket_id);",
        "CREATE INDEX IF NOT EXISTS idx_ai_run_log_created_at ON ai_run_log(created_at DESC);",
    ]

    # Таблица knowledge_base без колонки embedding (если pgvector недоступен)
    kb_create_no_vector = """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
            title VARCHAR(500) NOT NULL,
            content TEXT NOT NULL,
            short_answer TEXT,
            tags TEXT[],
            category VARCHAR(100),
            usage_count INTEGER DEFAULT 0,
            success_rate FLOAT DEFAULT 1.0,
            keywords TEXT[],
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            search_vector tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('simple', coalesce(title,'')), 'A') ||
                setweight(to_tsvector('simple', coalesce(content,'')), 'B')
            ) STORED
        );
        """

    with get_connection() as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                if not has_pgvector and ("vector(384)" in stmt or "embedding vector" in stmt):
                    continue
                if not has_pgvector and "CREATE TABLE IF NOT EXISTS knowledge_base" in stmt and "embedding" in stmt:
                    cur.execute(kb_create_no_vector)
                    continue
                cur.execute(stmt)

