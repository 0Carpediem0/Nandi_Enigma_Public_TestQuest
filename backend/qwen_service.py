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
    """Ленивая загрузка модели в процесс (один раз). Без скачивания: только кэш HF или QWEN_MODEL_PATH."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    model_path = os.getenv("QWEN_MODEL_PATH", "").strip()
    if model_path and os.path.isdir(model_path):
        model_arg = model_path
        logger.info("Loading Qwen from local path: %s", model_path)
    else:
        model_arg = os.getenv("QWEN_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
        logger.info("Loading Qwen from cache (offline): %s", model_arg)
        # Не качать: только из кэша. Если модели нет — будет ошибка, а не скачивание.
        os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        from transformers import pipeline
        _pipeline = pipeline(
            "text-generation",
            model=model_arg,
            torch_dtype="auto",
            device_map="auto",
            trust_remote_code=True,
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
            logger.warning("Qwen pipeline returned empty output")
            return None
        gen = out[0]
        if not isinstance(gen, dict) or "generated_text" not in gen:
            logger.warning("Qwen pipeline unexpected format: %s", type(gen))
            return None
        gt = gen["generated_text"]
        # Qwen2.5 Instruct: list сообщений, последний — ответ ассистента
        if isinstance(gt, list) and len(gt) > 0:
            last = gt[-1]
            if isinstance(last, dict):
                text = last.get("content") or last.get("text") or ""
                if text.strip():
                    return text.strip()
        # Иногда pipeline возвращает одну строку (весь текст)
        if isinstance(gt, str) and gt.strip():
            # Убираем промпт, оставляем только ответ ассистента
            for marker in (f"{IM_END}\n", "assistant\n", "assistant"):
                if marker in gt:
                    tail = gt.split(marker)[-1]
                    if tail.strip():
                        return tail.split(IM_END)[0].strip()
            return gt.strip()
        logger.warning("Qwen pipeline could not extract reply from: %s", type(gt))
        return None
    except Exception as e:
        logger.exception("Qwen in-process generation failed: %s", e)
        return None


# Демо-заглушка, когда Qwen выключен или недоступен — хоть что-то «от ИИ» в тикет
_DEMO_STUB_PHRASES = [
    "По вашему запросу: рекомендуем проверить раздел настройки и пункт 3.2 руководства. При необходимости уточните параметры.",
    "Обращение принято. Типовые шаги: проверка питания, перезапуск, сверка с руководством. Дополнительно можем уточнить по логам.",
    "Демо-ответ: по теме обращения — см. инструкцию, раздел «Неисправности». Если вопрос по калибровке — напишите модель прибора.",
]

def _demo_stub_reply(user_message: str) -> str:
    """Возвращает короткий «ответ» для демо, когда реальный Qwen недоступен."""
    msg = (user_message or "").strip()[:200]
    idx = hash(msg) % len(_DEMO_STUB_PHRASES)
    return _DEMO_STUB_PHRASES[idx]


def ask_qwen(system_prompt: str, user_message: str) -> str | None:
    """
    Генерация ответа Qwen. Режим: in-process (QWEN_USE_LOCAL=true), локальный HTTP или облако HF.
    Если Qwen выключен или запрос не удался — возвращается демо-заглушка (хоть что-то в черновик).
    """
    if not _is_enabled():
        logger.info("Qwen disabled, returning demo stub")
        return _demo_stub_reply(user_message)

    if _use_local_inprocess():
        result = _ask_qwen_inprocess(system_prompt, user_message)
        if result and result.strip():
            return result
        logger.warning("Qwen in-process returned empty, using demo stub")
        return _demo_stub_reply(user_message)

    cfg = _get_config()
    use_local = bool(cfg["base_url"])
    if not use_local and not cfg["token"]:
        logger.warning("HF_TOKEN not set and QWEN_BASE_URL empty, using demo stub")
        return _demo_stub_reply(user_message)

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
        return text if text else _demo_stub_reply(user_message)
    except (OSError, urllib.error.URLError) as e:
        logger.warning("Qwen API unreachable: %s", e)
        return _demo_stub_reply(user_message)
    except Exception as e:
        logger.exception("Qwen API request failed: %s", e)
        return _demo_stub_reply(user_message)
