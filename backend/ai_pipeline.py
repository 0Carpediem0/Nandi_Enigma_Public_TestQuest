from time import perf_counter

from ai_analyzer import analyze_email
from ai_config import AIConfig
from ai_generator import generate_draft
from ai_guardrails import apply_guardrails
from ai_retriever import retrieve_context


def _ms(start: float, end: float) -> int:
    return int((end - start) * 1000)


def run_ai_pipeline(email_item: dict) -> dict:
    total_start = perf_counter()

    analyzer_start = perf_counter()
    analyzed = analyze_email(email_item)
    analyzer_end = perf_counter()

    retrieval_start = perf_counter()
    question = str(email_item.get("body") or email_item.get("body_preview") or "")
    sources = retrieve_context(question=question, category=analyzed.get("category"))
    retrieval_end = perf_counter()

    generator_start = perf_counter()
    generated = generate_draft(
        question=question,
        category=analyzed.get("category") or "Общий запрос",
        context_items=sources,
    )
    generator_end = perf_counter()

    guard_start = perf_counter()
    merged = {
        "from_addr": str(email_item.get("from_addr") or "unknown"),
        "subject": str(email_item.get("subject") or "(без темы)"),
        "body_preview": str(email_item.get("body_preview") or "(пустое письмо)"),
        "category": analyzed.get("category"),
        "priority": analyzed.get("priority"),
        "tone": analyzed.get("tone"),
        "confidence": analyzed.get("confidence"),
        "needs_attention": analyzed.get("needs_attention"),
        "reasoning_short": analyzed.get("reasoning_short"),
        "sources": sources,
        "draft_answer": generated.get("draft_answer"),
        "model": generated.get("generator_model"),
        "pipeline_version": AIConfig.PIPELINE_VERSION,
    }
    guarded = apply_guardrails(merged)
    guard_end = perf_counter()
    total_end = perf_counter()

    timings = {
        "analyzer_ms": _ms(analyzer_start, analyzer_end),
        "retrieval_ms": _ms(retrieval_start, retrieval_end),
        "generator_ms": _ms(generator_start, generator_end),
        "guardrails_ms": _ms(guard_start, guard_end),
        "total_ms": _ms(total_start, total_end),
    }
    guarded["timings_ms"] = timings
    guarded["processing_time_ms"] = timings["total_ms"]
    guarded["analyzer_model"] = analyzed.get("analyzer_model")
    guarded["generator_model"] = generated.get("generator_model")
    guarded["fallback_used"] = bool(generated.get("fallback_used"))
    return guarded
