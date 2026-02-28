from pydantic import BaseModel, Field


class SendEmailRequest(BaseModel):
    to: str = Field(..., description="Адрес получателя")
    subject: str = Field(..., description="Тема письма")
    body: str = Field(..., description="Текст письма")
    body_html: str | None = Field(None, description="HTML-версия (опционально)")


class SendEmailResponse(BaseModel):
    ok: bool
    to: str | None = None
    error: str | None = None


class ProcessLatestEmailRequest(BaseModel):
    mailbox: str = Field("INBOX", description="Папка, из которой берём последнее письмо")
    operator_email: str | None = Field(
        None,
        description="Почта оператора. Если не передана, используется OPERATOR_EMAIL из окружения.",
    )


class ProcessLatestEmailResponse(BaseModel):
    ok: bool
    source_from: str
    source_subject: str
    operator_email: str
    ai_decision: str
    ai_draft_response: str
    sent_via_port: int | None = None
    error: str | None = None


class UpdateTicketRequest(BaseModel):
    client_name: str | None = None
    phone: str | None = None
    location_object: str | None = None
    serial_numbers: str | None = None
    device_type: str | None = None
    question: str | None = None
    answer: str | None = None
    status: str | None = None
    needs_attention: bool | None = None
    is_resolved: bool | None = None


class ReplyTicketRequest(BaseModel):
    to_email: str | None = Field(None, description="Если не задано, берется email клиента из тикета")
    subject: str | None = Field(None, description="Если не задано, будет Re: тема тикета")
    body: str = Field(..., description="Финальный ответ оператора")


class SaveToKbRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    short_answer: str | None = None
    category: str | None = None
    tags: list[str] | None = None


class KnowledgeBaseEntry(BaseModel):
    """Одна запись из поиска по базе знаний."""
    id: int
    title: str
    content: str
    short_answer: str | None = None
    category: str | None = None
    rank: float | None = None


class KnowledgeBaseSearchResponse(BaseModel):
    """Ответ API поиска по базе знаний."""
    query: str
    count: int
    entries: list[KnowledgeBaseEntry]


class KbAskRequest(BaseModel):
    """Запрос ответа на вопрос клиента (поиск в БЗ + Qwen)."""
    question: str = Field(..., min_length=1, description="Вопрос клиента")
    limit: int = Field(5, ge=1, le=10, description="Сколько записей из БЗ подставлять в контекст")


class KbAskResponse(BaseModel):
    """Ответ на вопрос: сгенерированный текст и источники из базы знаний."""
    question: str
    answer: str
    source_ids: list[int] = Field(default_factory=list, description="id записей knowledge_base, по которым сформирован ответ")
    fallback: bool = Field(False, description="True, если ответ взят из short_answer (Qwen недоступен или не вернул текст)")

