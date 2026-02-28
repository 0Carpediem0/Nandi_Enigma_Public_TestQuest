from ai_config import AIConfig
from repositories import search_kb_hybrid


def retrieve_context(question: str, category: str | None) -> list[dict]:
    if not AIConfig.RAG_ENABLED:
        return []
    rows = search_kb_hybrid(query_text=question, category=category, top_k=AIConfig.RETRIEVER_TOP_K)
    return [
        {
            "kb_id": row.get("id"),
            "title": row.get("title"),
            "short_answer": row.get("short_answer"),
            "category": row.get("category"),
            "tags": row.get("tags") or [],
        }
        for row in rows
    ]
