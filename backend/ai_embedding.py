import hashlib

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


def _project_to_384(values: list[float]) -> list[float]:
    if len(values) == 384:
        return values
    if len(values) > 384:
        return values[:384]
    return values + [0.0] * (384 - len(values))


def _hf_embedding(text: str) -> list[float]:
    tokenizer, model, torch_mod = _load_encoder()
    encoded = tokenizer(text, truncation=True, max_length=256, return_tensors="pt")
    if torch_mod.cuda.is_available():
        encoded = {k: v.to("cuda") for k, v in encoded.items()}

    with torch_mod.no_grad():
        output = model(**encoded)
        hidden = output.last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        pooled = torch_mod.nn.functional.normalize(pooled[0], p=2, dim=0)
    return _project_to_384(pooled.detach().cpu().tolist())


def text_to_vector_384(text: str) -> list[float]:
    if AIConfig.BERT_ENABLED:
        try:
            return _hf_embedding(text or "")
        except Exception:
            pass

    # Deterministic fallback embedding for environments without local model runtime.
    base = hashlib.sha256((text or "").encode("utf-8")).digest()
    raw = (base * ((384 // len(base)) + 1))[:384]
    return [((byte / 255.0) * 2.0) - 1.0 for byte in raw]
