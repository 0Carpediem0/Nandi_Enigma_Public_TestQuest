# Сборка с Qwen (torch + transformers). Долгая первая сборка — потом кэш.
# После запуска: http://localhost:8000 и http://localhost:8000/operator.html
FROM python:3.12-slim

WORKDIR /app

# Полный requirements — Qwen включён (.env задаёт QWEN_ENABLED / QWEN_USE_LOCAL)
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r ./backend/requirements.txt

COPY backend/ ./backend/
COPY front/   ./front/

WORKDIR /app/backend
EXPOSE 8000
ENV PORT=8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
