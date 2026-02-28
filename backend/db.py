import os
from contextlib import contextmanager

import psycopg


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
            ai_suggested_answer TEXT,
            ai_category VARCHAR(100),
            ai_priority VARCHAR(50),
            ai_tone VARCHAR(50),
            needs_attention BOOLEAN DEFAULT FALSE,
            is_resolved BOOLEAN DEFAULT FALSE,
            message_id VARCHAR(255) UNIQUE,
            in_reply_to VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            resolved_at TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);",
        "CREATE INDEX IF NOT EXISTS idx_tickets_client_email ON tickets(client_email);",
        "CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC);",
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
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_base(category);",
        "CREATE INDEX IF NOT EXISTS idx_kb_active ON knowledge_base(is_active);",
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)

