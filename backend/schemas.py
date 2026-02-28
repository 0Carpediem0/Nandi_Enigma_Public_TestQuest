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
    ai_confidence: float | None = None
    ai_category: str | None = None
    ai_priority: str | None = None
    needs_attention: bool = False
    auto_send_allowed: bool = False
    auto_send_reason: str | None = None
    ai_sources: list[dict] = Field(default_factory=list)
    pipeline_version: str | None = None
    timings_ms: dict = Field(default_factory=dict)
    sent_via_port: int | None = None
    error: str | None = None


class ProcessBatchEmailsRequest(BaseModel):
    mailbox: str = Field("INBOX", description="Папка, из которой берём письма")
    limit: int = Field(5, ge=1, le=50, description="Сколько последних писем обработать")
    operator_email: str | None = Field(
        None,
        description="Почта оператора. Если не передана, используется OPERATOR_EMAIL из окружения.",
    )
    notify_operator: bool = Field(False, description="Отправить оператору краткий digest обработки")


class ProcessBatchEmailsResponse(BaseModel):
    ok: bool
    processed_count: int
    ticket_ids: list[int] = Field(default_factory=list)
    failed_count: int = 0
    operator_email: str | None = None
    digest_sent: bool = False


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

