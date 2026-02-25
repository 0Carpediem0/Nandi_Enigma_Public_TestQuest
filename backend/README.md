# Backend — почтовый API для AI-агента

Почта: **yegor.starkov.06@mail.ru** (Mail.ru). Учётные данные — в `backend/.env` (см. `.env.example`).

## API для AI-агента

После запуска сервис доступен по адресу `http://localhost:8000`. Документация: **http://localhost:8000/docs**.

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка работы и подключения к IMAP/SMTP |
| POST | `/send` | Отправить письмо (тело: `to`, `subject`, `body`, опционально `body_html`) |
| GET | `/emails` | Входящие (параметры: `limit`, `mailbox`, по умолчанию INBOX) |
| GET | `/emails/sent` | Отправленные (параметр: `limit`) |

### Пример вызова от агента

**Отправка письма:**
```http
POST /send
Content-Type: application/json

{"to": "kiryavseznayka@mail.ru", "subject": "Тема", "body": "Текст письма"}
```

**Чтение входящих:**
```http
GET /emails?limit=10
```

**Чтение отправленных:**
```http
GET /emails/sent?limit=10
```

## Локальный запуск

```bash
cd backend
cp .env.example .env   # указать EMAIL_PASSWORD
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Или: `python app.py`

## Docker

Из корня репозитория:

```bash
cp backend/.env.example backend/.env   # отредактировать
docker compose up --build
```

API: **http://localhost:8000**. Переменные окружения передаются из `backend/.env`.

## Модуль email_service (внутренний)

- `send_email(to_addr, subject, body, body_html=None)` — отправка (SMTP)
- `fetch_recent_emails(limit=10, mailbox="INBOX")` — входящие (IMAP)
- `fetch_recent_emails_sent(limit=10)` — отправленные
- `check_connection()` — проверка IMAP/SMTP

Переменные: `EMAIL_USER`, `EMAIL_PASSWORD`, `IMAP_HOST`, `IMAP_PORT`, `SMTP_HOST`, `SMTP_PORT` (см. `.env.example`).
