# -*- coding: utf-8 -*-
"""
Сервис эмбеддингов через Hugging Face Inference API (feature-extraction).
Используется для векторного поиска по базе знаний (семантика).
"""
import json
import logging
import os
import urllib.request
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
# Модель по умолчанию: 384 измерения, мультиязычная (в т.ч. русский)
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384


def _get_config() -> dict:
    return {
        "model": os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip(),
        "token": os.getenv("HF_TOKEN", "").strip(),
    }


def get_embedding(text: str) -> list[float] | None:
    """
    Возвращает вектор эмбеддинга для текста (384 измерений для MiniLM).
    При ошибке или отсутствии HF_TOKEN возвращает None.
    """
    text = (text or "").strip()
    if not text:
        return None
    cfg = _get_config()
    if not cfg["token"]:
        logger.warning("HF_TOKEN not set, cannot get embedding")
        return None

    url = f"{HF_INFERENCE_URL}/{cfg['model']}"
    body = json.dumps({"inputs": text[:8192]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {cfg['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        if isinstance(out, list):
            if len(out) > 0 and isinstance(out[0], (list, tuple)):
                return list(out[0])
            if len(out) > 0 and isinstance(out[0], (int, float)):
                return list(out)
        return None
    except Exception as e:
        logger.exception("Embedding API failed: %s", e)
        return None
