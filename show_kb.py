# -*- coding: utf-8 -*-
"""Вывод содержимого knowledge_base в UTF-8."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / "backend" / ".env", encoding="utf-8")
import psycopg

def main():
    conn = psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        dbname=os.getenv("PGDATABASE", "test"),
        options="-c client_encoding=UTF8",
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, category, left(content, 120) as content_preview,
               array_length(tags, 1) as tags_count
        FROM knowledge_base ORDER BY id
    """)
    rows = cur.fetchall()
    out = sys.stdout
    out.reconfigure(encoding="utf-8")
    out.write(f"knowledge_base: {len(rows)} записей\n\n")
    for r in rows:
        id_, title, category, content_preview, tags_count = r
        out.write(f"id={id_} category={category or ''} tags={tags_count or 0}\n")
        out.write(f"  title: {title}\n")
        out.write(f"  content: {(content_preview or '')[:100]}...\n\n")
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'knowledge_base' ORDER BY ordinal_position")
    out.write("Колонки таблицы knowledge_base:\n")
    for r in cur.fetchall():
        out.write(f"  {r[0]}: {r[1]}\n")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
