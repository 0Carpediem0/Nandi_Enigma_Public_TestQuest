// Относительный URL: работает и локально, и в Docker
const API_BASE = typeof window !== 'undefined' && window.location ? window.location.origin : '';
const API_TICKETS = `${API_BASE}/tickets`;

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let msg = 'Ошибка API';
    const contentType = response.headers.get('content-type') || '';
    const body = await response.text();
    if (contentType.includes('application/json')) {
      try {
        const data = JSON.parse(body);
        msg = data.detail || msg;
      } catch (_) {}
    } else if (body) {
      msg = body;
    }
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = response.status;
    throw err;
  }
  const contentType = response.headers.get('content-type') || '';
  return contentType.includes('application/json') ? response.json() : response.text();
}

function setStatus(text) {
  const node = document.getElementById('operatorStatus');
  if (node) node.textContent = text;
}

function setIngestStatus(text) {
  const node = document.getElementById('ingestStatus');
  if (node) node.textContent = text;
}

async function loadTickets() {
  const select = document.getElementById('ticketSelect');
  if (!select) return;

  try {
    const tickets = await apiFetch(`${API_TICKETS}?limit=100`);
    select.innerHTML = '';

    tickets.forEach((ticket) => {
      const option = document.createElement('option');
      option.value = String(ticket.id);
      option.textContent = `#${ticket.id} | ${ticket.email} | ${ticket.status} | conf=${ticket.ai_confidence ?? '-'}`;
      option.dataset.status = ticket.status || 'new';
      option.dataset.ai = ticket.ai_response || '';
      option.dataset.category = ticket.category || '-';
      option.dataset.priority = ticket.priority || '-';
      option.dataset.confidence = String(ticket.ai_confidence ?? '-');
      option.dataset.needsAttention = String(Boolean(ticket.needs_attention));
      option.dataset.autoSendAllowed = String(Boolean(ticket.auto_send_allowed));
      option.dataset.autoSendReason = ticket.auto_send_reason || '-';
      select.appendChild(option);
    });

    if (tickets.length > 0) {
      hydrateFromSelected();
      setStatus(`Загружено тикетов: ${tickets.length}`);
    } else {
      setStatus('Тикеты не найдены');
    }
  } catch (error) {
    const msg = error.message || '';
    setStatus(msg.includes('Failed to fetch') || msg.includes('NetworkError')
      ? 'Сервис недоступен. Убедитесь, что бэкенд запущен. В разработке.'
      : `Тикеты не загружены. ${msg}`);
  }
}

function hydrateFromSelected() {
  const select = document.getElementById('ticketSelect');
  const status = document.getElementById('statusSelect');
  const reply = document.getElementById('replyText');
  if (!select || !status || !reply) return;
  const current = select.selectedOptions[0];
  if (!current) return;
  status.value = current.dataset.status || 'new';
  reply.value = current.dataset.ai || '';
  setStatus(
    [
      `AI: ${current.dataset.category || '-'}`,
      `priority=${current.dataset.priority || '-'}`,
      `confidence=${current.dataset.confidence || '-'}`,
      `needs_attention=${current.dataset.needsAttention || '-'}`,
      `auto_send=${current.dataset.autoSendAllowed || '-'}`,
      `reason=${current.dataset.autoSendReason || '-'}`,
    ].join(' | ')
  );
}

async function updateTicket() {
  const select = document.getElementById('ticketSelect');
  const status = document.getElementById('statusSelect');
  const reply = document.getElementById('replyText');
  if (!select || !status || !reply || !select.value) return;

  setStatus('Сохраняю тикет...');
  try {
    await apiFetch(`${API_TICKETS}/${select.value}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        status: status.value,
        answer: reply.value,
      }),
    });
    setStatus('Тикет обновлён');
    await loadTickets();
  } catch (error) {
    const msg = error.message || '';
    setStatus(error.status === 503 ? 'Сохранение тикета: в разработке.' : `Ошибка: ${msg}`);
  }
}

async function sendReply() {
  const select = document.getElementById('ticketSelect');
  const reply = document.getElementById('replyText');
  if (!select || !reply || !select.value) return;

  setStatus('Отправляю ответ...');
  try {
    await apiFetch(`${API_TICKETS}/${select.value}/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ body: reply.value }),
    });
    setStatus('Ответ отправлен');
    await loadTickets();
  } catch (error) {
    const msg = error.message || '';
    setStatus(error.status === 503
      ? 'Отправка ответа клиенту будет доступна после настройки почты. В разработке.'
      : `Ошибка: ${msg}`);
  }
}

async function saveToKb() {
  const select = document.getElementById('ticketSelect');
  if (!select || !select.value) return;

  setStatus('Сохраняю в KB...');
  try {
    await apiFetch(`${API_TICKETS}/${select.value}/save-to-kb`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({}),
    });
    setStatus('Кейс сохранён в KB');
    await loadTickets();
  } catch (error) {
    const msg = error.message || '';
    setStatus(error.status === 503 ? 'Сохранение в базу знаний: в разработке.' : `Ошибка: ${msg}`);
  }
}

async function processDemoEmail() {
  setIngestStatus('Обработка демо-письма ИИ…');
  const btn = document.getElementById('processDemoBtn');
  if (btn) btn.disabled = true;
  try {
    const data = await apiFetch(`${API_BASE}/mvp/process-demo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({}),
    });
    setIngestStatus(`Готово. Тикет создан. От: ${data.source_from || '-'}, тема: ${data.source_subject || '-'}. Обновите список тикетов.`);
    await loadTickets();
  } catch (error) {
    setIngestStatus(`Ошибка: ${error.message || 'неизвестно'}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function processLatestEmail() {
  const operatorEmail = document.getElementById('operatorEmail')?.value?.trim();
  setIngestStatus('Обработка последнего письма ИИ…');
  const btn = document.getElementById('processLatestBtn');
  if (btn) btn.disabled = true;
  try {
    const body = operatorEmail
      ? { mailbox: 'INBOX', operator_email: operatorEmail }
      : { mailbox: 'INBOX' };
    const data = await apiFetch(`${API_BASE}/mvp/process-latest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify(body),
    });
    setIngestStatus(`Готово. От: ${data.source_from || '-'}, тема: ${data.source_subject || '-'}. Черновик отправлен оператору.`);
    await loadTickets();
  } catch (error) {
    const msg = error.message || '';
    if (error.status === 503 || msg.includes('не настроено') || msg.includes('В разработке')) {
      setIngestStatus('Обработка почты ИИ будет доступна после настройки почты. Сделаем в будущем.');
    } else if (msg.includes('409') || msg.includes('уже')) {
      setIngestStatus('Письмо уже было обработано ранее.');
    } else {
      setIngestStatus(`Ошибка: ${msg}`);
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function ingestEmails() {
  setIngestStatus('Забираю входящие…');
  setIngestLoading(true);
  try {
    const data = await apiFetch(`${API_BASE}/emails/ingest?limit=20&mailbox=INBOX`, { method: 'POST' });
    setIngestStatus(`Создано тикетов: ${data.ingested_count || 0}`);
    await loadTickets();
  } catch (error) {
    setIngestStatus(`Ошибка: ${error.message}`);
  } finally {
    setIngestLoading(false);
  }
}

async function processLatestEmail() {
  const operatorEmail = document.getElementById('operatorEmail')?.value?.trim();
  setIngestStatus('Обработка последнего письма с помощью ИИ…');
  setIngestLoading(true);
  try {
    const body = operatorEmail
      ? { mailbox: 'INBOX', operator_email: operatorEmail }
      : { mailbox: 'INBOX' };
    const data = await apiFetch(`${API_BASE}/mvp/process-latest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify(body),
    });
    setIngestStatus(
      `Готово. От: ${data.source_from || '-'}, тема: ${data.source_subject || '-'}. Черновик отправлен оператору.`
    );
    await loadTickets();
  } catch (error) {
    setIngestStatus(`Ошибка: ${error.message}`);
  } finally {
    setIngestLoading(false);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const select = document.getElementById('ticketSelect');
  const updateBtn = document.getElementById('updateBtn');
  const replyBtn = document.getElementById('replyBtn');
  const kbBtn = document.getElementById('kbBtn');
  const processLatestBtn = document.getElementById('processLatestBtn');

  if (select) select.addEventListener('change', hydrateFromSelected);
  if (updateBtn) updateBtn.addEventListener('click', updateTicket);
  if (replyBtn) replyBtn.addEventListener('click', sendReply);
  if (kbBtn) kbBtn.addEventListener('click', saveToKb);
  const processDemoBtn = document.getElementById('processDemoBtn');
  if (processDemoBtn) processDemoBtn.addEventListener('click', processDemoEmail);
  if (processLatestBtn) processLatestBtn.addEventListener('click', processLatestEmail);

  loadTickets();
});
