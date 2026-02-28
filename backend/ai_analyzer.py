from ai_config import AIConfig

_TOKENIZER = None
_MODEL = None
_TORCH = None


def _load_encoder():
    global _TOKENIZER, _MODEL, _TORCH
    if _TOKENIZER is not None and _MODEL is not None and _TORCH is not None:
        return _TOKENIZER, _MODEL, _TORCH

    import torch
    from transformers import AutoModel, AutoTokenizer

    _TORCH = torch
    _TOKENIZER = AutoTokenizer.from_pretrained(AIConfig.BERT_MODEL_NAME)
    _MODEL = AutoModel.from_pretrained(AIConfig.BERT_MODEL_NAME)
    _MODEL.eval()
    if torch.cuda.is_available():
        _MODEL = _MODEL.to("cuda")
    return _TOKENIZER, _MODEL, _TORCH


def _mean_pool(hidden_state, attention_mask, torch_mod):
    mask = attention_mask.unsqueeze(-1).expand(hidden_state.size()).float()
    summed = (hidden_state * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


def _embed_text(text: str):
    tokenizer, model, torch_mod = _load_encoder()
    encoded = tokenizer(
        text,
        truncation=True,
        max_length=256,
        return_tensors="pt",
    )
    if torch_mod.cuda.is_available():
        encoded = {k: v.to("cuda") for k, v in encoded.items()}

    with torch_mod.no_grad():
        output = model(**encoded)
        vector = _mean_pool(output.last_hidden_state, encoded["attention_mask"], torch_mod)[0]
        vector = torch_mod.nn.functional.normalize(vector, p=2, dim=0)
    return vector


def _classify_with_embeddings(text: str) -> dict:
    torch_mod = _load_encoder()[2]
    sample_vec = _embed_text(text)
    profile_map = {
        "incident": "Критическая ошибка, авария, не работает устройство, срочный инцидент",
        "consulting": "Нужна инструкция, как подключить, как настроить, консультация",
        "general": "Общий вопрос по поддержке и эксплуатации оборудования",
    }
    scores = {}
    for key, profile_text in profile_map.items():
        profile_vec = _embed_text(profile_text)
        sim = torch_mod.dot(sample_vec, profile_vec).item()
        scores[key] = sim

    winner = max(scores, key=scores.get)
    conf = max(min((scores[winner] + 1.0) / 2.0, 0.99), 0.5)

    if winner == "incident":
        return {
            "category": "Инцидент / Неисправность",
            "priority": "Высокий",
            "tone": "Негативный",
            "confidence": conf,
            "needs_attention": True,
            "reasoning_short": "BERT-классификация: обращение ближе к профилю инцидента.",
        }
    if winner == "consulting":
        return {
            "category": "Консультация / Настройка",
            "priority": "Средний",
            "tone": "Нейтральный",
            "confidence": conf,
            "needs_attention": False,
            "reasoning_short": "BERT-классификация: запрос похож на инструкцию/настройку.",
        }
    return {
        "category": "Общий запрос",
        "priority": "Низкий",
        "tone": "Нейтральный",
        "confidence": conf,
        "needs_attention": False,
        "reasoning_short": "BERT-классификация: общий информационный запрос.",
    }


def _heuristic_analysis(text: str, model: str) -> dict:
    low = text.lower()
    if any(word in low for word in ("не работает", "ошибка", "авар", "срочно", "слом")):
        return {
            "category": "Инцидент / Неисправность",
            "priority": "Высокий",
            "tone": "Негативный",
            "confidence": 0.86,
            "needs_attention": True,
            "reasoning_short": "Обнаружены маркеры инцидента и срочности.",
            "analyzer_model": model,
        }
    if any(word in low for word in ("как", "инструкция", "подключ", "настрой")):
        return {
            "category": "Консультация / Настройка",
            "priority": "Средний",
            "tone": "Нейтральный",
            "confidence": 0.8,
            "needs_attention": False,
            "reasoning_short": "Письмо похоже на запрос инструкции или помощи с настройкой.",
            "analyzer_model": model,
        }
    return {
        "category": "Общий запрос",
        "priority": "Низкий",
        "tone": "Нейтральный",
        "confidence": 0.68,
        "needs_attention": False,
        "reasoning_short": "Явных признаков критичного инцидента не найдено.",
        "analyzer_model": model,
    }


def analyze_email(email_item: dict) -> dict:
    subject = str(email_item.get("subject") or "").strip()
    body_preview = str(email_item.get("body_preview") or "").strip()
    text = f"{subject}\n{body_preview}"[: AIConfig.BERT_MAX_CHARS]

    if not AIConfig.BERT_ENABLED:
        return _heuristic_analysis(text, "heuristic-analyzer")

    try:
        analyzed = _classify_with_embeddings(text)
        analyzed["analyzer_model"] = AIConfig.BERT_MODEL_NAME
        return analyzed
    except Exception:
        # If local model/GPU is unavailable, keep the service alive with deterministic fallback.
        return _heuristic_analysis(text, f"{AIConfig.BERT_MODEL_NAME}:fallback-heuristic")
