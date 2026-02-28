# -*- coding: utf-8 -*-
"""
Сервис вызова Qwen через Hugging Face Inference API.
Используется для генерации ответа клиенту на основе контекста из базы знаний.
"""
import logging
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent / ".env"
    if _env.exists():
        load_dotenv(_env)
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

HF_INFERENCE_URL = "https://api.inference.huggingface.co/models"
# Qwen2.5 Instruct chat template
IM_START = "<|im_start|>"
IM_END = "<|im_end|>"


def _is_enabled() -> bool:
    return os.getenv("QWEN_ENABLED", "").lower() in ("true", "1", "yes")


def _get_config() -> dict:
    return {
        "model": os.getenv("QWEN_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct"),
        "max_new_tokens": int(os.getenv("QWEN_MAX_NEW_TOKENS", "256")),
        "temperature": float(os.getenv("QWEN_TEMPERATURE", "0.3")),
        "token": os.getenv("HF_TOKEN", "").strip(),
    }


def _build_prompt(system: str, user_message: str) -> str:
    """Формирует промпт в формате Qwen2.5 Instruct (chat)."""
    parts = [
        f"{IM_START}system\n{system}{IM_END}\n",
        f"{IM_START}user\n{user_message}{IM_END}\n",
        f"{IM_START}assistant\n",
    ]
    return "".join(parts)


def ask_qwen(system_prompt: str, user_message: str) -> str | None:
    """
    Отправляет запрос к Qwen через Hugging Face Inference API.
    system_prompt — контекст (например, фрагменты из базы знаний).
    user_message — вопрос клиента.
    Возвращает сгенерированный ответ или None при ошибке/отключении.
    """
    if not _is_enabled():
        logger.info("Qwen disabled (QWEN_ENABLED != true)")
        return None
    cfg = _get_config()
    if not cfg["token"]:
        logger.warning("HF_TOKEN not set, skipping Qwen call")
        return None

    import urllib.request
    import json

    url = f"{HF_INFERENCE_URL}/{cfg['model']}"
    prompt = _build_prompt(system_prompt, user_message)
    body = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": cfg["max_new_tokens"],
            "temperature": cfg["temperature"],
            "return_full_text": False,
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {cfg['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        if isinstance(out, list) and len(out) > 0 and isinstance(out[0], dict):
            text = out[0].get("generated_text") or ""
        elif isinstance(out, dict) and "generated_text" in out:
            text = out["generated_text"]
        else:
            text = str(out) if out else ""
        # Обрезать по маркеру конца ответа
        if IM_END in text:
            text = text.split(IM_END)[0]
        return text.strip() if text else None
    except Exception as e:
        logger.exception("Qwen API request failed: %s", e)
        return None
