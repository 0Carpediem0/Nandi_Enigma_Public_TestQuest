@echo off
REM Запуск локального Qwen через vLLM (порт 8080). Нужны: Python, vLLM, GPU с достаточным VRAM.
REM Установка: pip install vllm
REM После запуска бэкенд (app) подключается к http://localhost:8080 при QWEN_BASE_URL=http://localhost:8080 и QWEN_OPENAI_API=true

set MODEL=Qwen/Qwen2.5-7B-Instruct
set PORT=8080

echo Starting Qwen on http://localhost:%PORT% ...
vllm serve %MODEL% --port %PORT%
if errorlevel 1 (
  echo.
  echo If vllm is not installed: pip install vllm
  echo If you use a smaller model, edit MODEL in this script or run:
  echo   vllm serve Qwen/Qwen2.5-0.5B-Instruct --port 8080
  pause
)
