import os


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, str(default))).strip().lower()
    return value in {"1", "true", "yes", "on"}


class AIConfig:
    PIPELINE_VERSION = os.getenv("AI_PIPELINE_VERSION", "v1")

    BERT_ENABLED = _env_bool("BERT_ENABLED", True)
    RAG_ENABLED = _env_bool("RAG_ENABLED", True)
    QWEN_ENABLED = _env_bool("QWEN_ENABLED", True)
    AUTO_SEND_ENABLED = _env_bool("AUTO_SEND_ENABLED", False)

    BERT_MODEL_NAME = os.getenv("BERT_MODEL_NAME", "bert-base-multilingual-cased")
    QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "Qwen/Qwen2.5-3B-Instruct")

    RETRIEVER_TOP_K = int(os.getenv("RETRIEVER_TOP_K", "3"))
    AUTO_SEND_CONFIDENCE_THRESHOLD = float(os.getenv("AUTO_SEND_CONFIDENCE_THRESHOLD", "0.92"))
    MAX_DRAFT_CHARS = int(os.getenv("MAX_DRAFT_CHARS", "1200"))

    # Local inference parameters
    BERT_MAX_CHARS = int(os.getenv("BERT_MAX_CHARS", "2000"))
    QWEN_MAX_NEW_TOKENS = int(os.getenv("QWEN_MAX_NEW_TOKENS", "220"))
    QWEN_TEMPERATURE = float(os.getenv("QWEN_TEMPERATURE", "0.2"))
