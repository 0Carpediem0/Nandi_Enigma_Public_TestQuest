FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY email_service.py main.py ./

# Запуск проверки почты (сокомандники могут менять на свой entrypoint)
CMD ["python", "main.py"]
