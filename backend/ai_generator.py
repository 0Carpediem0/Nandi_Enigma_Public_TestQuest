from ai_config import AIConfig

_GENERATOR = None


def _get_generator():
    global _GENERATOR
    if _GENERATOR is not None:
        return _GENERATOR

    from transformers import pipeline

    _GENERATOR = pipeline(
        "text-generation",
        model=AIConfig.QWEN_MODEL_NAME,
        device_map="auto",
    )
    return _GENERATOR


def _fallback_draft() -> str:
    return (
        "Здравствуйте! Получили ваше обращение. "
        "Пожалуйста, уточните модель устройства и серийный номер. "
        "Если проблема срочная, оператор подключится в ближайшее время."
    )


def generate_draft(question: str, category: str, context_items: list[dict]) -> dict:
    model_name = AIConfig.QWEN_MODEL_NAME if AIConfig.QWEN_ENABLED else "template-generator"
    if not AIConfig.QWEN_ENABLED:
        return {"draft_answer": _fallback_draft(), "generator_model": model_name, "fallback_used": True}

    context_chunks = []
    for item in context_items[:3]:
        line = item.get("short_answer") or item.get("title") or ""
        if line:
            context_chunks.append(f"- {line}")
    context_text = "\n".join(context_chunks) if context_chunks else "- Контекст не найден"

    prompt = (
        "Ты ассистент техподдержки. Напиши короткий профессиональный ответ на русском языке.\n"
        "Нельзя выдумывать факты, опирайся только на контекст.\n\n"
        f"Категория: {category}\n"
        f"Вопрос клиента: {question}\n"
        f"Контекст:\n{context_text}\n\n"
        "Ответ:"
    )

    try:
        generator = _get_generator()
        generated = generator(
            prompt,
            max_new_tokens=AIConfig.QWEN_MAX_NEW_TOKENS,
            max_length=None,
            temperature=AIConfig.QWEN_TEMPERATURE,
            do_sample=AIConfig.QWEN_TEMPERATURE > 0,
            return_full_text=False,
        )
        text = str(generated[0].get("generated_text") or "").strip()
        if not text:
            return {"draft_answer": _fallback_draft(), "generator_model": model_name, "fallback_used": True}
        return {"draft_answer": text, "generator_model": model_name, "fallback_used": False}
    except Exception:
        if context_items:
            best = context_items[0]
            short = best.get("short_answer") or best.get("title") or ""
            draft = (
                "Здравствуйте! Спасибо за обращение.\n\n"
                f"По вашей категории «{category}» рекомендуем: {short}\n\n"
                "Если после этих шагов проблема сохраняется, ответьте на письмо — передадим оператору."
            )
            return {"draft_answer": draft, "generator_model": f"{model_name}:fallback-template", "fallback_used": True}
        return {"draft_answer": _fallback_draft(), "generator_model": f"{model_name}:fallback-template", "fallback_used": True}
