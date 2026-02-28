# -*- coding: utf-8 -*-
"""
Парсер библиотеки файлов ЭРИС (eriskip.com).
Собирает базу знаний из метаданных и из содержимого PDF-файлов
для оператора/нейросети-ассистента.
"""

import os
import re
import csv
import time
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

BASE_URL = "https://eriskip.com"
FILES_URL = "https://eriskip.com/ru/files-library"
DEFAULT_CATEGORY = 14  # Руководство по эксплуатации
PER_PAGE = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
CONTENT_PREVIEW_LEN = 4000   # символов превью в CSV
DOWNLOAD_DELAY = 1.0         # пауза между загрузками PDF (сек)


def safe_filename(s):
    """Имя файла без недопустимых символов."""
    s = re.sub(r"[^\w\s\-\.]", "", s, flags=re.U)
    s = re.sub(r"\s+", "_", s).strip("_")[:80]
    return s or "doc"


def download_pdf(url, session):
    """Скачать PDF по URL, вернуть bytes или None."""
    if not url or not url.strip().lower().endswith(".pdf"):
        return None
    try:
        r = session.get(url, timeout=60, stream=True)
        r.raise_for_status()
        ct = (r.headers.get("Content-Type") or "").lower()
        if "pdf" not in ct and "octet" not in ct:
            return None
        return r.content
    except Exception as e:
        print(f"  Ошибка загрузки PDF: {e}")
        return None


def extract_text_from_pdf(pdf_bytes):
    """Извлечь текст из PDF (PyMuPDF). Возвращает строку или пустую при ошибке."""
    if fitz is None:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for page in doc:
            parts.append(page.get_text(sort=True))
        doc.close()
        text = "\n".join(parts).strip()
        return text
    except Exception as e:
        print(f"  Ошибка извлечения текста из PDF: {e}")
        return ""


def get_total_pages(soup):
    """Определить количество страниц из блока summary (Показаны записи 1-15 из 100)."""
    summary = soup.select_one("#files-list .summary")
    if not summary:
        return 1
    # В HTML: <b>1-15</b> из <b>100</b> — берём последний <b> с числом
    b_tags = summary.find_all("b")
    for b in reversed(b_tags):
        t = b.get_text(strip=True)
        if t.isdigit():
            total = int(t)
            return max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return 1


def get_category_name(soup):
    """Название текущей категории из активной ссылки в сайдбаре."""
    active = soup.select_one(".files-categories li.active a")
    if active:
        return active.get_text(strip=True)
    return "Руководство по эксплуатации"


def parse_page(html, category_name, page_num):
    """Из одной HTML-страницы извлечь список файлов."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for div in soup.select("#files-list div.item"):
        info = div.select_one(".info")
        if not info:
            continue
        title_el = info.select_one("h4.title a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        file_url = title_el.get("href")
        if file_url and not file_url.startswith("http"):
            file_url = urljoin(BASE_URL, file_url)
        badge = info.select_one("span.badge")
        format_size = badge.get_text(strip=True) if badge else ""
        fmt, size = "", ""
        if format_size:
            parts = format_size.split("/", 1)
            fmt = parts[0].strip() if parts else ""
            size = parts[1].strip() if len(parts) > 1 else ""
        desc_el = info.select_one("div.description")
        description = (desc_el.get_text(strip=True) if desc_el else "") or ""
        data_key = div.get("data-key", "")
        items.append({
            "id": data_key,
            "category": category_name,
            "title": title,
            "format": fmt,
            "size": size,
            "description": description,
            "file_url": file_url or "",
            "page_num": page_num,
        })
    return items


def extract_keywords(title, description):
    """
    Извлечь ключевые слова/модели для поиска ассистентом.
    Например: ЭРИС-110, ДГС ЭРИС-210, ИП-330 и т.д.
    """
    text = f"{title} {description}".upper()
    keywords = set()
    # Модели вида ЭРИС-110, ЭРИС-210-2, ДГС ЭРИС-230-3
    for m in re.finditer(r"(?:ДГС|СГМ|ПГ|ДГК)[\s\-]*ЭРИС[\-\s]*\d+[\-\w]*", text, re.I):
        keywords.add(m.group(0).strip())
    for m in re.finditer(r"ЭРИС[\s\-]*\d+[\-\w]*", text, re.I):
        keywords.add(m.group(0).strip())
    for m in re.finditer(r"ИП[\s\-]*\d+", text, re.I):
        keywords.add(m.group(0).strip())
    for m in re.finditer(r"ДГК[\s\-]*\w+", text, re.I):
        keywords.add(m.group(0).strip())
    # Общие термины
    if "РУКОВОДСТВО" in text:
        keywords.add("руководство по эксплуатации")
    if "МОДЕМ" in text or "МОДЕМ" in title.upper():
        keywords.add("модем")
    if "РЕТРАНСЛЯТОР" in text:
        keywords.add("ретранслятор")
    return " | ".join(sorted(keywords)) if keywords else ""


def fetch_category(category_id=DEFAULT_CATEGORY, max_pages=None):
    """Собрать все записи по категории (с пагинацией)."""
    session = requests.Session()
    session.headers.update(HEADERS)
    all_items = []
    page = 1
    category_name = ""
    while True:
        url = f"{FILES_URL}?category={category_id}&page={page}"
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            r.encoding = "utf-8"
        except Exception as e:
            print(f"Ошибка запроса {url}: {e}")
            break
        soup = BeautifulSoup(r.text, "html.parser")
        if page == 1:
            category_name = get_category_name(soup)
            total_pages = get_total_pages(soup)
            if max_pages is not None:
                total_pages = min(total_pages, max_pages)
            print(f"Категория: {category_name}, страниц: {total_pages}")
        items = parse_page(r.text, category_name, page)
        if not items:
            break
        for it in items:
            it["keywords"] = extract_keywords(it["title"], it["description"])
        all_items.extend(items)
        if max_pages and page >= max_pages:
            break
        # следующая страница
        total_pages = get_total_pages(soup)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.5)
    return all_items


def enrich_items_with_pdf_content(items, session, out_dir, delay=DOWNLOAD_DELAY, max_files=None):
    """
    Для каждого элемента: скачать PDF, извлечь текст, сохранить в .txt,
    добавить в элемент content_file, content_preview, content_length.
    max_files: обработать не более N документов (для теста).
    """
    if fitz is None:
        print("PyMuPDF не установлен. Установите: pip install pymupdf")
        return
    os.makedirs(out_dir, exist_ok=True)
    total = len(items)
    if max_files is not None:
        total = min(total, max_files)
        print(f"Обработка только первых {total} документов (--max-files).")
    for i, item in enumerate(items, 1):
        if max_files is not None and i > max_files:
            break
        url = item.get("file_url") or ""
        title = item.get("title", "")
        doc_id = item.get("id", i)
        print(f"  [{i}/{total}] {title[:60]}...")
        pdf_bytes = download_pdf(url, session)
        if not pdf_bytes:
            item["content_file"] = ""
            item["content_preview"] = ""
            item["content_length"] = 0
            continue
        text = extract_text_from_pdf(pdf_bytes)
        item["content_length"] = len(text)
        if not text:
            item["content_file"] = ""
            item["content_preview"] = ""
            continue
        slug = safe_filename(title)
        fname = f"{doc_id}_{slug}.txt"
        fpath = os.path.join(out_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(text)
        item["content_file"] = fname
        item["content_preview"] = (text[:CONTENT_PREVIEW_LEN] + "...") if len(text) > CONTENT_PREVIEW_LEN else text
        time.sleep(delay)
    for item in items:
        item.setdefault("content_file", "")
        item.setdefault("content_length", 0)
        item.setdefault("content_preview", "")
    print(f"Тексты сохранены в папку: {out_dir}")


def build_knowledge_base_table(rows, out_csv, out_tsv=None, with_content=True):
    """
    Таблица базы знаний для ассистента/оператора.
    Колонки подходят для RAG, чат-бота, поиска по ключевым словам.
    """
    fieldnames = [
        "id",
        "category",
        "title",
        "format",
        "size",
        "description",
        "file_url",
        "keywords",
        "answer_template",
        "page_num",
    ]
    if with_content:
        fieldnames.extend(["content_file", "content_length", "content_preview"])
    for r in rows:
        # Шаблон ответа для оператора/нейросети
        r["answer_template"] = (
            f"Документ: «{r['title']}». "
            + (f"Описание: {r['description']}. " if r.get("description") else "")
            + f"Формат: {r.get('format', '')} {r.get('size', '')}. "
            + (f"Ссылка для скачивания: {r.get('file_url', '')}" if r.get("file_url") else "")
        ).strip()
        if with_content:
            r.setdefault("content_file", "")
            r.setdefault("content_length", 0)
            r.setdefault("content_preview", "")

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"Сохранено CSV: {out_csv} ({len(rows)} записей)")

    if out_tsv:
        with open(out_tsv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        print(f"Сохранено TSV: {out_tsv}")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Парсер библиотеки файлов ЭРИС — база знаний из метаданных и из содержимого PDF")
    ap.add_argument("--category", type=int, default=DEFAULT_CATEGORY, help="ID категории (по умолчанию 14)")
    ap.add_argument("--max-pages", type=int, default=None, help="Макс. число страниц (для теста)")
    ap.add_argument("--csv", default="база_знаний_ЭРИС.csv", help="Файл CSV базы знаний")
    ap.add_argument("--tsv", default="", help="Дополнительно сохранить TSV")
    ap.add_argument("--no-content", action="store_true", help="Не скачивать PDF и не извлекать текст (только метаданные со страницы)")
    ap.add_argument("--content-dir", default="база_знаний_тексты", help="Папка для сохранения извлечённых текстов из PDF")
    ap.add_argument("--delay", type=float, default=DOWNLOAD_DELAY, help="Пауза между загрузками PDF (сек)")
    ap.add_argument("--max-files", type=int, default=None, help="Обработать не более N PDF (для теста)")
    args = ap.parse_args()

    rows = fetch_category(category_id=args.category, max_pages=args.max_pages)
    if not rows:
        print("Ни одной записи не получено.")
        return

    with_content = not args.no_content
    if with_content and rows:
        print("Скачивание PDF и извлечение текста...")
        session = requests.Session()
        session.headers.update(HEADERS)
        enrich_items_with_pdf_content(rows, session, args.content_dir, delay=args.delay, max_files=args.max_files)

    build_knowledge_base_table(rows, args.csv, args.tsv or None, with_content=with_content)


if __name__ == "__main__":
    main()
