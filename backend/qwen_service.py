# -*- coding: utf-8 -*-
"""
Сервис вызова Qwen: in-process (transformers), локальный HTTP или Hugging Face API.
При QWEN_USE_LOCAL=true модель грузится в процесс и вызывается без внешнего API.
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
IM_START = "<|im_start|>"
IM_END = "<|im_end|>"

# Глобальный pipeline для in-process (ленивая загрузка)
_pipeline = None


def _is_enabled() -> bool:
    return os.getenv("QWEN_ENABLED", "").lower() in ("true", "1", "yes")


def _use_local_inprocess() -> bool:
    """Модель в том же процессе (transformers), без HTTP и без облака."""
    return os.getenv("QWEN_USE_LOCAL", "").lower() in ("true", "1", "yes")


def _get_config() -> dict:
    base_url = os.getenv("QWEN_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("QWEN_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
    use_openai_api = os.getenv("QWEN_OPENAI_API", "").lower() in ("true", "1", "yes")
    return {
        "base_url": base_url,
        "model": model,
        "use_openai_api": use_openai_api,
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


def _get_local_pipeline():
    """Ленивая загрузка модели в процесс (один раз)."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    model_name = os.getenv("QWEN_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
    logger.info("Loading Qwen in-process: %s (first call may download)", model_name)
    try:
        from transformers import pipeline
        _pipeline = pipeline(
            "text-generation",
            model=model_name,
            torch_dtype="auto",
            device_map="auto",
            model_kwargs={"trust_remote_code": True},
        )
        return _pipeline
    except Exception as e:
        logger.exception("Failed to load Qwen in-process: %s", e)
        return None


def _ask_qwen_inprocess(system_prompt: str, user_message: str) -> str | None:
    """Вызов модели в том же процессе, без API."""
    pipe = _get_local_pipeline()
    if pipe is None:
        return None
    model_name = os.getenv("QWEN_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
    max_new_tokens = int(os.getenv("QWEN_MAX_NEW_TOKENS", "256"))
    temperature = float(os.getenv("QWEN_TEMPERATURE", "0.3"))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    try:
        out = pipe(
            messages,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else 0.01,
            top_p=0.95,
            pad_token_id=pipe.tokenizer.eos_token_id,
        )
        if not out or not isinstance(out, list) or len(out) == 0:
            return None
        gen = out[0]
        if isinstance(gen, dict) and "generated_text" in gen:
            gt = gen["generated_text"]
            # Qwen2 Instruct: list сообщений, нужен последний (assistant)
            if isinstance(gt, list) and len(gt) > 0 and isinstance(gt[-1], dict):
                return (gt[-1].get("content") or "").strip()
            if isinstance(gt, str):
                return gt.strip()
        return None
    except Exception as e:
        logger.exception("Qwen in-process generation failed: %s", e)
        return None


def ask_qwen(system_prompt: str, user_message: str) -> str | None:
    """
    Генерация ответа Qwen. Режим: in-process (QWEN_USE_LOCAL=true), локальный HTTP или облако HF.
    """
    if not _is_enabled():
        logger.info("Qwen disabled (QWEN_ENABLED != true)")
        return None

    if _use_local_inprocess():
        return _ask_qwen_inprocess(system_prompt, user_message)

    cfg = _get_config()
    use_local = bool(cfg["base_url"])
    if not use_local and not cfg["token"]:
        logger.warning("HF_TOKEN not set and QWEN_BASE_URL empty, skipping Qwen call")
        return None

    import json
    import urllib.error
    import urllib.request

    if use_local and cfg.get("use_openai_api"):
        # vLLM и другие серверы с OpenAI-совместимым API (/v1/chat/completions)
        url = f"{cfg['base_url']}/v1/chat/completions"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        body = {
            "model": cfg["model"].split("/")[-1] if "/" in cfg["model"] else cfg["model"],
            "messages": messages,
            "max_tokens": cfg["max_new_tokens"],
            "temperature": cfg["temperature"],
        }
    elif use_local:
        url = f"{cfg['base_url']}/{cfg['model']}".rstrip("/") if cfg["model"] else cfg["base_url"]
        prompt = _build_prompt(system_prompt, user_message)
        body = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": cfg["max_new_tokens"],
                "temperature": cfg["temperature"],
                "return_full_text": False,
            },
        }
    else:
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
    headers = {"Content-Type": "application/json"}
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        if use_local and cfg.get("use_openai_api"):
            text = None
            if isinstance(out, dict) and "choices" in out and len(out["choices"]) > 0:
                msg = out["choices"][0].get("message") or {}
                text = msg.get("content") or ""
            text = (text or "").strip()
        else:
            if isinstance(out, list) and len(out) > 0 and isinstance(out[0], dict):
                text = out[0].get("generated_text") or ""
            elif isinstance(out, dict) and "generated_text" in out:
                text = out["generated_text"]
            else:
                text = str(out) if out else ""
            if IM_END in text:
                text = text.split(IM_END)[0]
            text = (text or "").strip()
        return text if text else None
    except (OSError, urllib.error.URLError) as e:
        # Сеть/DNS (getaddrinfo failed, timeout, connection refused) — без traceback
        logger.warning("Qwen API unreachable: %s", e)
        return None
    except Exception as e:
        logger.exception("Qwen API request failed: %s", e)
        return None
