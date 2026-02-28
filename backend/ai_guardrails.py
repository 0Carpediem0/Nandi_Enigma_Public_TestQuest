from ai_config import AIConfig


def apply_guardrails(ai_result: dict) -> dict:
    draft = str(ai_result.get("draft_answer") or "").strip()
    confidence = float(ai_result.get("confidence") or 0.0)
    needs_attention = bool(ai_result.get("needs_attention"))

    auto_send_allowed = (
        AIConfig.AUTO_SEND_ENABLED
        and not needs_attention
        and confidence >= AIConfig.AUTO_SEND_CONFIDENCE_THRESHOLD
    )

    reason = None
    if not AIConfig.AUTO_SEND_ENABLED:
        reason = "auto_send_disabled_by_flag"
    elif needs_attention:
        reason = "needs_operator_attention"
    elif confidence < AIConfig.AUTO_SEND_CONFIDENCE_THRESHOLD:
        reason = "low_confidence"

    if len(draft) > AIConfig.MAX_DRAFT_CHARS:
        draft = draft[: AIConfig.MAX_DRAFT_CHARS].rstrip() + "..."

    blocked_patterns = ("пароль администратора", "переведите деньги")
    if any(p in draft.lower() for p in blocked_patterns):
        ai_result["needs_attention"] = True
        auto_send_allowed = False
        reason = "blocked_by_safety_pattern"

    ai_result["draft_answer"] = draft
    ai_result["auto_send_allowed"] = auto_send_allowed
    ai_result["auto_send_reason"] = reason
    return ai_result
