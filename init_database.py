import argparse
import getpass
import os
import sys
import traceback
from pathlib import Path
from typing import Iterable

# Подгрузить backend/.env для PGHOST, PGPASSWORD и т.д.
_backend_env = Path(__file__).resolve().parent / "backend" / ".env"
if _backend_env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_backend_env, override=True)
    except ImportError:
        pass

import psycopg
from psycopg import Connection as PgConnection
from psycopg import sql


def exec_many(conn: PgConnection, statements: Iterable[str], title: str) -> None:
    print(f"\n== {title} ==")
    with conn.cursor() as cur:
        for idx, stmt in enumerate(statements, start=1):
            short = stmt.strip().splitlines()[0][:90]
            print(f"[{idx}] {short} ...")
            cur.execute(stmt)
    print("OK")


def ensure_database(
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str,
) -> None:
    conn = psycopg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname="postgres",
        options="-c client_encoding=UTF8",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone():
                print(f"База {db_name!r} уже существует.")
                return

            cur.execute(
                sql.SQL(
                    "CREATE DATABASE {} WITH ENCODING 'UTF8' TEMPLATE template0"
                ).format(sql.Identifier(db_name))
            )
            print(f"Создана база {db_name!r}.")
    finally:
        conn.close()


def create_schema(
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str,
    drop_existing: bool,
    seed: bool,
) -> None:
    conn = psycopg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=db_name,
        options="-c client_encoding=UTF8",
    )
    conn.autocommit = True

    try:
        if drop_existing:
            exec_many(
                conn,
                [
                    "DROP TABLE IF EXISTS feedback CASCADE;",
                    "DROP TABLE IF EXISTS email_log CASCADE;",
                    "DROP TABLE IF EXISTS knowledge_base CASCADE;",
                    "DROP TABLE IF EXISTS tickets CASCADE;",
                    "DROP TABLE IF EXISTS operators CASCADE;",
                ],
                "Удаление старых таблиц",
            )

        # Расширения (vector опционален — если нет pgvector, таблица knowledge_base создаётся без колонки embedding)
        has_pgvector = True
        with conn.cursor() as cur:
            print("\n== Расширения ==")
            print("[1] CREATE EXTENSION IF NOT EXISTS pg_trgm ...")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

            print("[2] CREATE EXTENSION IF NOT EXISTS vector ...")
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                print("OK")
            except Exception as e:
                if "vector" in str(e).lower() or "not available" in str(e).lower():
                    has_pgvector = False
                    print("(пропущено: pgvector не установлен)")
                else:
                    raise

        schema_statements = [
            """
            CREATE TABLE IF NOT EXISTS operators (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY,
                client_email VARCHAR(255) NOT NULL,
                client_name VARCHAR(255),
                subject VARCHAR(500),
                question TEXT,
                answer TEXT,
                status VARCHAR(50) DEFAULT 'new',
                ai_confidence FLOAT,
                ai_processing_time INTEGER,
                ai_suggested_answer TEXT,
                ai_model VARCHAR(50),
                ai_tone VARCHAR(50),
                ai_priority VARCHAR(50),
                ai_sources JSONB DEFAULT '[]'::jsonb,
                ai_reasoning_short TEXT,
                pipeline_version VARCHAR(50),
                auto_send_allowed BOOLEAN DEFAULT FALSE,
                auto_send_reason TEXT,
                tags TEXT[],
                category VARCHAR(100),
                operator_id INTEGER REFERENCES operators(id) ON DELETE SET NULL,
                needs_attention BOOLEAN DEFAULT FALSE,
                is_resolved BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                resolved_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                search_vector tsvector GENERATED ALWAYS AS (
                    setweight(to_tsvector('simple', coalesce(question,'')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(answer,'')), 'B')
                ) STORED
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);",
            "CREATE INDEX IF NOT EXISTS idx_tickets_client_email ON tickets(client_email);",
            "CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC);",
            "CREATE INDEX IF NOT EXISTS idx_tickets_resolved_at ON tickets(resolved_at DESC);",
            "CREATE INDEX IF NOT EXISTS idx_tickets_is_resolved ON tickets(is_resolved);",
            "CREATE INDEX IF NOT EXISTS idx_tickets_needs_attention ON tickets(needs_attention);",
            "CREATE INDEX IF NOT EXISTS idx_tickets_tags ON tickets USING GIN (tags);",
            "CREATE INDEX IF NOT EXISTS idx_tickets_search ON tickets USING GIN (search_vector);",
            """
            CREATE TABLE IF NOT EXISTS email_log (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                raw_from VARCHAR(255) NOT NULL,
                raw_to VARCHAR(255) NOT NULL,
                raw_subject VARCHAR(500),
                raw_body TEXT,
                raw_html TEXT,
                message_id VARCHAR(255),
                in_reply_to VARCHAR(255),
                direction VARCHAR(10) DEFAULT 'incoming',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_email_log_ticket ON email_log(ticket_id);",
            "CREATE INDEX IF NOT EXISTS idx_email_log_message_id ON email_log(message_id);",
            "CREATE INDEX IF NOT EXISTS idx_email_log_direction ON email_log(direction);",
            "CREATE INDEX IF NOT EXISTS idx_email_log_created ON email_log(created_at DESC);",
            """
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id SERIAL PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                content TEXT NOT NULL,
                short_answer TEXT,
                tags TEXT[],
                category VARCHAR(100),
                embedding vector(384),
                keywords TEXT[],
                usage_count INTEGER DEFAULT 0,
                success_rate FLOAT DEFAULT 1.0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                search_vector tsvector GENERATED ALWAYS AS (
                    setweight(to_tsvector('simple', coalesce(title,'')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(content,'')), 'B')
                ) STORED
            );
            """,
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
            "CREATE INDEX IF NOT EXISTS idx_kb_tags ON knowledge_base USING GIN (tags);",
            "CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_base(category);",
            "CREATE INDEX IF NOT EXISTS idx_kb_is_active ON knowledge_base(is_active);",
            "CREATE INDEX IF NOT EXISTS idx_kb_search ON knowledge_base USING GIN (search_vector);",
            "CREATE INDEX IF NOT EXISTS idx_kb_usage ON knowledge_base(usage_count DESC);",
            "CREATE INDEX IF NOT EXISTS idx_ai_run_log_ticket_id ON ai_run_log(ticket_id);",
            "CREATE INDEX IF NOT EXISTS idx_ai_run_log_created_at ON ai_run_log(created_at DESC);",
        ]

        KB_TABLE_NO_VECTOR = """
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id SERIAL PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                content TEXT NOT NULL,
                short_answer TEXT,
                tags TEXT[],
                category VARCHAR(100),
                keywords TEXT[],
                usage_count INTEGER DEFAULT 0,
                success_rate FLOAT DEFAULT 1.0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                search_vector tsvector GENERATED ALWAYS AS (
                    setweight(to_tsvector('simple', coalesce(title,'')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(content,'')), 'B')
                ) STORED
            );
            """
        if not has_pgvector:
            schema_statements = [
                (KB_TABLE_NO_VECTOR if "embedding vector(384)" in s and "knowledge_base" in s else s)
                for s in schema_statements
            ]

        schema_statements.extend([
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                operator_id INTEGER REFERENCES operators(id) ON DELETE SET NULL,
                kb_id INTEGER REFERENCES knowledge_base(id) ON DELETE SET NULL,
                is_helpful BOOLEAN,
                rating INTEGER CHECK (rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_feedback_ticket ON feedback(ticket_id);",
            "CREATE INDEX IF NOT EXISTS idx_feedback_kb ON feedback(kb_id);",
            "CREATE INDEX IF NOT EXISTS idx_feedback_helpful ON feedback(is_helpful);",
        ])

        exec_many(conn, schema_statements, "Создание таблиц и индексов")

        if seed:
            seed_statements = [
                """
                INSERT INTO operators (email, name)
                VALUES ('operator@support.ru', 'Иван Петров'),
                       ('alex@support.ru', 'Алексей Смирнов')
                ON CONFLICT (email) DO NOTHING;
                """,
                """
                INSERT INTO knowledge_base (
                    title, content, short_answer, tags, category, keywords
                )
                SELECT
                    'Ошибка E21 на котле ThermoMax',
                    'Код E21 означает перегрев теплообменника. Проверьте давление в системе, '
                    || 'циркуляционный насос и очистите фильтр обратки.',
                    'Проверьте давление и циркуляцию, затем перезапустите котел.',
                    ARRAY['boiler', 'E21', 'overheat'],
                    'hardware',
                    ARRAY['перегрев', 'давление', 'насос', 'фильтр']
                WHERE NOT EXISTS (
                    SELECT 1 FROM knowledge_base WHERE title = 'Ошибка E21 на котле ThermoMax'
                );
                """,
                """
                INSERT INTO knowledge_base (
                    title, content, short_answer, tags, category, keywords
                )
                SELECT
                    'Сброс пароля в личном кабинете',
                    'Для сброса пароля используйте ссылку "Забыли пароль?" на странице входа. '
                    || 'Письмо со ссылкой действует 15 минут.',
                    'Используйте "Забыли пароль?" и ссылку из письма.',
                    ARRAY['account', 'password', 'login'],
                    'software',
                    ARRAY['пароль', 'вход', 'личный кабинет']
                WHERE NOT EXISTS (
                    SELECT 1 FROM knowledge_base WHERE title = 'Сброс пароля в личном кабинете'
                );
                """,
                """
                INSERT INTO tickets (
                    client_email, client_name, subject, question, answer, status, tags, category,
                    operator_id, needs_attention, is_resolved, created_at, resolved_at
                )
                SELECT
                    'ivanov@example.com',
                    'Иван Иванов',
                    'Насос X-100 не включается',
                    'Здравствуйте! Насос X-100 перестал запускаться. Мигает красная лампочка.',
                    'Проверьте предохранитель F2 на блоке питания.',
                    'resolved',
                    ARRAY['pump', 'electrical', 'X-100'],
                    'hardware',
                    (SELECT id FROM operators WHERE email = 'operator@support.ru'),
                    FALSE,
                    TRUE,
                    '2024-02-20 10:30:00',
                    '2024-02-20 11:15:00'
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM tickets
                    WHERE client_email = 'ivanov@example.com'
                      AND subject = 'Насос X-100 не включается'
                );
                """,
                """
                INSERT INTO tickets (
                    client_email, client_name, subject, question, status, tags, category,
                    operator_id, needs_attention, is_resolved
                )
                SELECT
                    'petrova@example.com',
                    'Мария Петрова',
                    'Ошибка E21 на котле',
                    'Добрый день. После включения через 2 минуты появляется ошибка E21.',
                    'in_progress',
                    ARRAY['boiler', 'E21'],
                    'hardware',
                    (SELECT id FROM operators WHERE email = 'alex@support.ru'),
                    TRUE,
                    FALSE
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM tickets
                    WHERE client_email = 'petrova@example.com'
                      AND subject = 'Ошибка E21 на котле'
                );
                """,
                """
                INSERT INTO email_log (
                    ticket_id, raw_from, raw_to, raw_subject, raw_body, message_id, direction
                )
                SELECT
                    t.id,
                    'petrova@example.com',
                    'support@company.ru',
                    'Re: Ошибка E21 на котле',
                    'Пробовала перезапуск, ошибка осталась. Давление 0.8 bar.',
                    '<msg-e21-001@example.com>',
                    'incoming'
                FROM tickets t
                WHERE t.client_email = 'petrova@example.com'
                  AND t.subject = 'Ошибка E21 на котле'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM email_log el
                      WHERE el.message_id = '<msg-e21-001@example.com>'
                  );
                """,
                """
                INSERT INTO feedback (
                    ticket_id, operator_id, kb_id, is_helpful, rating, comment
                )
                SELECT
                    t.id,
                    o.id,
                    kb.id,
                    TRUE,
                    5,
                    'Ответ помог, проблема решена быстро.'
                FROM tickets t
                JOIN operators o ON o.email = 'operator@support.ru'
                JOIN knowledge_base kb ON kb.title = 'Ошибка E21 на котле ThermoMax'
                WHERE t.client_email = 'ivanov@example.com'
                  AND t.subject = 'Насос X-100 не включается'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM feedback f
                      WHERE f.ticket_id = t.id
                  );
                """,
            ]
            exec_many(conn, seed_statements, "Тестовые данные")

        print("\nГотово. База и таблицы созданы.")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Создание БД support schema в PostgreSQL."
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument(
        "--password",
        default=os.getenv("PGPASSWORD"),
        help="Пароль PostgreSQL (если не указан, будет запрошен интерактивно)",
    )
    parser.add_argument("--db", default="test", help="Имя целевой базы")
    parser.add_argument(
        "--create-db",
        action="store_true",
        help="Создать базу, если ее нет",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Удалить существующие таблицы перед созданием",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Заполнить тестовыми данными",
    )

    args = parser.parse_args()
    if not args.password:
        args.password = getpass.getpass("Введите пароль PostgreSQL: ")

    try:
        if args.create_db:
            ensure_database(args.host, args.port, args.user, args.password, args.db)

        create_schema(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            db_name=args.db,
            drop_existing=args.drop_existing,
            seed=args.seed,
        )
        return 0
    except Exception as exc:
        traceback.print_exc()
        print("\nОШИБКА:", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
