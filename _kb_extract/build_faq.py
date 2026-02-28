# -*- coding: utf-8 -*-
"""
Строит FAQ по руководствам ЭРИС: читает каждый .txt, извлекает разделы из оглавления,
определяет, на какие вопросы отвечает раздел, формирует пары вопрос–ответ.
Запуск из папки _kb_extract: python build_faq.py
"""

import csv
import os
import re

CSV_IN = "база_знаний_ЭРИС.csv"
TEXTS_DIR = "база_знаний_тексты"
FAQ_CSV_OUT = "faq_база_знаний.csv"
FAQ_ENCODING = "utf-8-sig"
# Сколько символов с начала файла читать для поиска оглавления
TOC_READ_LIMIT = 22000


# Паттерны: ключевые слова в названии раздела -> шаблон вопроса
SECTION_TO_QUESTION = [
    (r"калибровк|установк[аи]\s+нуля|градуировк", "Как выполнить калибровку (установку нуля)?"),
    (r"монтаж|подключен|схем[ыа]\s+подключен|электрическое подключение", "Как выполнить монтаж и подключение?"),
    (r"протокол\s+обмена|интерфейс\s+rs|modbus|rs-?485", "Какой протокол обмена (RS485/Modbus)?"),
    (r"ошибк|неисправность|диагностик|индикаци|световая индикация", "Как устранить неисправность или расшифровать индикацию?"),
    (r"назначение\s+изделия|назначение\s+системы", "Для чего предназначено изделие?"),
    (r"техническое\s+обслуживание|ремонт\s+системы|обслуживание\s+и\s+ремонт", "Как проводить техническое обслуживание и ремонт?"),
    (r"использование\s+по\s+назначению|эксплуатаци\s+системы|эксплуатаци\s+прибора", "Как эксплуатировать изделие?"),
    (r"гарантия\s+изготовителя|гарантии\s+изготовителя", "Какие гарантии изготовителя?"),
    (r"комплектность|состав\s+системы|состав\s+устройства", "Какая комплектность (состав изделия)?"),
    (r"устройство\s+и\s+работа|описание\s+и\s+работа", "Как устроено и как работает изделие?"),
    (r"меры\s+безопасности|безопасность|требования\s+к\s+безопасности", "Какие меры безопасности необходимо соблюдать?"),
    (r"маркировка|пломбирование", "Маркировка и пломбирование"),
    (r"габарит|чертеж|установочные размеры", "Габаритные размеры и чертежи"),
    (r"диапазон\s+измерен|пределы\s+допускаемой|погрешность", "Диапазоны измерений и погрешность"),
    (r"поверк|поверка", "Поверка и интервал между поверками"),
    (r"транспортирование|хранение", "Транспортирование и хранение"),
    (r"упаковка", "Упаковка изделия"),
    (r"программное\s+обеспечение|ПО\s+газоанализатора|меню|настройк", "Программное обеспечение и настройка"),
    (r"номинальная\s+статическая|функция\s+преобразования|токовы\s+выход", "Токовый выход и функция преобразования"),
    (r"газы\s+определяемые|сенсор\s+горючих", "Какие газы определяет сенсор?"),
]


def _short_title(title: str) -> str:
    """Краткое название изделия из заголовка документа."""
    t = title.strip()
    for prefix in ("Руководство по эксплуатации ", "Руководство по эксплуатации\n"):
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
    if t.endswith(" Руководство по эксплуатации"):
        t = t[: -len(" Руководство по эксплуатации")].strip()
    return t or title.strip()[:60]


def _extract_toc_sections(text: str) -> list[str]:
    """Извлекает названия разделов из оглавления (Содержание/СОДЕРЖАНИЕ)."""
    if not text or len(text) < 50:
        return []
    head = text[:TOC_READ_LIMIT]
    toc_start = re.search(r"СОДЕРЖАНИЕ|Содержание", head, re.I)
    if not toc_start:
        return []
    start = toc_start.end()
    # Берём кусок после "Содержание" до явного конца оглавления (Введение, строка с большим номером страницы и т.д.)
    chunk = head[start : start + 8000]
    sections = []
    for line in chunk.split("\n"):
        line = line.strip()
        if not line or len(line) < 3:
            continue
        # Убрать номера страниц и мусор в конце (....... 12, 35Подпись, дубл. №)
        line = re.sub(r"[.\s]+\d{1,3}\s*$", "", line).strip()
        line = re.sub(r"\d{1,3}(Подпись|дубл|Инв|№|Лит\.?|Лист).*$", "", line, flags=re.I).strip()
        if not line or len(line) < 4:
            continue
        # Строка оглавления: начинается с цифры (1.2 ...) или "Приложение А ..."
        if re.match(r"^\d+[\s\.]+", line) or re.match(r"^Приложение\s+[А-Яа-я]", line):
            # Объединить переносы типа "Приложение А Диапазоны ... \n основной погрешности"
            if sections and not re.match(r"^\d+[\s\.]+", line) and not line.startswith("Приложение"):
                if len(line) < 50 and not line.endswith("."):
                    sections[-1] = sections[-1] + " " + line
                    continue
            if len(line) > 5 and line not in sections:
                sections.append(line)
    return sections


def _section_to_question(section_title: str) -> str | None:
    """По названию раздела возвращает шаблон вопроса или None."""
    lower = section_title.lower()
    for pattern, question in SECTION_TO_QUESTION:
        if re.search(pattern, lower):
            return question
    return None


def _build_faq_from_doc(
    title: str,
    file_url: str,
    answer_template: str,
    content_file: str,
    texts_dir: str,
) -> list[dict]:
    """Читает .txt руководства, извлекает разделы, формирует список FAQ-записей."""
    product = _short_title(title)
    link = answer_template if answer_template else f"Документ: «{title}». Ссылка: {file_url}"
    faq_entries = []

    path = os.path.join(texts_dir, content_file) if content_file else None
    if not path or not os.path.isfile(path):
        # Нет файла — одна запись «где скачать»
        faq_entries.append({
            "question_template": f"Где скачать руководство по эксплуатации {product}?",
            "answer_template": link,
            "category": "Руководство по эксплуатации",
            "tags": product,
        })
        return faq_entries

    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        faq_entries.append({
            "question_template": f"Где скачать руководство по эксплуатации {product}?",
            "answer_template": link,
            "category": "Руководство по эксплуатации",
            "tags": product,
        })
        return faq_entries

    sections = _extract_toc_sections(text)
    seen_questions = set()

    for section in sections:
        q = _section_to_question(section)
        if not q or q in seen_questions:
            continue
        seen_questions.add(q)
        answer = f"См. раздел «{section}» в руководстве по эксплуатации {product}. {link}"
        faq_entries.append({
            "question_template": f"{q} — {product}",
            "answer_template": answer,
            "category": "Руководство по эксплуатации",
            "tags": product,
        })

    # Если по оглавлению ничего не нашли — одна общая запись
    if not faq_entries:
        faq_entries.append({
            "question_template": f"Где скачать руководство по эксплуатации {product}?",
            "answer_template": link,
            "category": "Руководство по эксплуатации",
            "tags": product,
        })

    return faq_entries


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, CSV_IN)
    texts_dir = os.path.join(script_dir, TEXTS_DIR)
    out_path = os.path.join(script_dir, FAQ_CSV_OUT)

    if not os.path.isfile(csv_path):
        print(f"Файл не найден: {csv_path}")
        return

    # Загрузить CSV
    rows = []
    with open(csv_path, "r", encoding=FAQ_ENCODING) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append(row)

    all_faq = []
    for row in rows:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        content_file = (row.get("content_file") or "").strip()
        file_url = (row.get("file_url") or "").strip()
        answer_template = (row.get("answer_template") or "").strip()
        category = (row.get("category") or "Руководство по эксплуатации").strip()
        keywords = (row.get("keywords") or "").strip()

        entries = _build_faq_from_doc(
            title=title,
            file_url=file_url,
            answer_template=answer_template,
            content_file=content_file,
            texts_dir=texts_dir,
        )
        for e in entries:
            e["category"] = category
            if keywords:
                e["tags"] = (e.get("tags") or "") + (" | " + keywords if e.get("tags") else keywords)
        all_faq.extend(entries)

    with open(out_path, "w", newline="", encoding=FAQ_ENCODING) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["question_template", "answer_template", "category", "tags"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(all_faq)

    print(f"Обработано документов: {len(rows)}, записей FAQ: {len(all_faq)}. Сохранено: {out_path}")


if __name__ == "__main__":
    main()
