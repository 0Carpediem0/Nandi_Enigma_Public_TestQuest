# Backend — почтовый API для AI-агента

Почта: **Rambler**. Учётные данные — в `backend/.env` (см. `.env.example`).

## API для AI-агента

После запуска сервис доступен по адресу `http://localhost:8000`. Документация: **http://localhost:8000/docs**.

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка работы и подключения к IMAP/SMTP |
| POST | `/send` | Отправить письмо (тело: `to`, `subject`, `body`, опционально `body_html`) |
| GET | `/emails` | Входящие (параметры: `limit`, `mailbox`, по умолчанию INBOX) |
| GET | `/emails/sent` | Отправленные (параметр: `limit`) |
| POST | `/emails/ingest` | Забрать письма из IMAP и создать/обновить тикеты в БД |
| GET | `/tickets` | Список тикетов для web UI |
| GET | `/tickets/{id}` | Детали тикета |
| PATCH | `/tickets/{id}` | Обновление тикета оператором |
| POST | `/tickets/{id}/reply` | Отправка финального ответа клиенту |
| POST | `/tickets/{id}/save-to-kb` | Сохранение кейса в базу знаний |
| GET | `/tickets/export` | Экспорт тикетов в CSV |
| POST | `/mvp/process-latest` | MVP-конвейер: взять последнее письмо -> AI-заглушка -> отправить оператору |

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

**MVP-конвейер (последнее входящее -> оператор):**
```http
POST /mvp/process-latest
Content-Type: application/json

{"mailbox": "INBOX", "operator_email": "operator@example.com"}
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

Поднимутся сервисы:
- `backend` — API на `http://localhost:8000`
- `postgres` — БД на `localhost:5432`

Переменные окружения передаются из `backend/.env` (`EMAIL_*`, `IMAP_*`, `SMTP_*`, `OPERATOR_EMAIL`, `PG*`).

## Быстрый smoke-сценарий

1. `POST /emails/ingest?limit=5` — подтянуть свежие письма в таблицу `tickets`.
2. `GET /tickets` — убедиться, что тикеты есть в UI-формате.
3. `POST /tickets/{id}/reply` — отправить ответ клиенту.
4. `POST /tickets/{id}/save-to-kb` — сохранить кейс в `knowledge_base`.

## Модуль email_service (внутренний)

- `send_email(to_addr, subject, body, body_html=None)` — отправка (SMTP)
- `fetch_recent_emails(limit=10, mailbox="INBOX")` — входящие (IMAP)
- `fetch_recent_emails_sent(limit=10)` — отправленные
- `check_connection()` — проверка IMAP/SMTP

Переменные: `EMAIL_USER`, `EMAIL_PASSWORD`, `IMAP_HOST`, `IMAP_PORT`, `SMTP_HOST`, `SMTP_PORT`, `OPERATOR_EMAIL` (см. `.env.example`).
