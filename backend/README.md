# Backend — почтовый сервис (IMAP / SMTP)

Почта по умолчанию: **yegor.starkov.06@mail.ru** (Mail.ru). Учётные данные — через переменные окружения или `backend/.env`.

---

## Где лежит письмо и как им пользоваться

- **Где лежит:** Письма хранятся **на почтовом сервере** (у VK — на их серверах), в папке **INBOX** (входящие). В нашем проекте писем нет — мы только подключаемся по протоколу **IMAP** и забираем список/тела писем по запросу.
- **Как посмотреть пришедшее письмо:**  
  - Через CLI: из папки `backend` выполнить  
    `python cli.py list`  
    (опционально: `python cli.py list INBOX 20` — папка и количество).  
  - В коде: `from email_service import fetch_recent_emails` → `fetch_recent_emails(limit=10)` — вернёт список словарей с полями `subject`, `from_addr`, `date`, `body_preview`.

## Как отправлять письма с этой почты и писать конкретным адресам

- **С этой почты** отправка идёт с адреса, указанного в `EMAIL_USER` (по умолчанию jimbeez@vk.com). Сервер отдаёт письмо по **SMTP**.
- **Конкретному адресу:** в первом аргументе передаёшь адрес получателя.
  - **Через CLI:**  
    `python cli.py send "получатель@example.com" "Тема письма" "Текст письма"`
  - **В коде:**  
    `send_email("получатель@example.com", "Тема", "Текст письма")`  
  Несколько получателей — вызвать `send_email` несколько раз с разными `to_addr` (или доработать функцию, чтобы принимала список адресов).

---

## Локальный запуск (без Docker)

```bash
cd backend
cp .env.example .env   # отредактировать EMAIL_PASSWORD и при необходимости хосты
pip install -r requirements.txt
python main.py
```

## Запуск через Docker (для сокомандников)

Из корня репозитория:

```bash
# 1. Создать backend/.env из примера и указать пароль
cp backend/.env.example backend/.env

# 2. Собрать и запустить
docker compose up --build
```

Или только бэкенд:

```bash
cd backend
docker build -t enigma-backend .
docker run --env-file .env enigma-backend
```

## CLI (посмотреть письма / отправить)

```bash
cd backend
python cli.py list              # последние 10 писем из INBOX
python cli.py list INBOX 20     # 20 писем из INBOX
python cli.py send "коллега@gmail.com" "Тема" "Привет, текст письма"
```

## API модуля `email_service`

- **`fetch_recent_emails(limit=10, mailbox="INBOX")`** — получить последние письма (IMAP).
- **`send_email(to_addr, subject, body, body_html=None)`** — отправить письмо (SMTP) на адрес `to_addr`.
- **`check_connection()`** — проверка подключения к IMAP/SMTP (для healthcheck).

Переменные окружения: `EMAIL_USER`, `EMAIL_PASSWORD`, `IMAP_HOST`, `IMAP_PORT`, `SMTP_HOST`, `SMTP_PORT` (см. `.env.example`).

---

## Если письма по SMTP не приходят (Mail.ru)

Mail.ru может **принимать** письмо по SMTP (скрипт пишет «Отправлено»), но **не доставлять** его ни в папку получателя, ни в «Отправленные». Это ограничение/политика провайдера (репутация IP, блокировки и т.п.).

**Что сделать:** Запусти `python example_usage.py` — там есть блок **«Тест: отправка письма СЕБЕ»**. Письмо уходит на твой же ящик (yegor.starkov.06@mail.ru).  
- Если **себе пришло** — SMTP работает, а до Gmail/других не доходит (проверь спам у получателя или используй другой SMTP для отправки).  
- Если **себе не пришло** — Mail.ru, скорее всего, не доставляет письма, отправленные с программ. Тогда для **отправки** имеет смысл использовать другой ящик с рабочим SMTP (например Gmail с паролем приложения или Yandex).
