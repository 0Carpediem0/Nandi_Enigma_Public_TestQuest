const API_BASE = 'http://localhost:8000';
const API_TICKETS = `${API_BASE}/tickets`;

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || 'Ошибка API');
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
      option.textContent = `#${ticket.id} | ${ticket.email} | ${ticket.status}`;
      option.dataset.status = ticket.status || 'new';
      option.dataset.ai = ticket.ai_response || '';
      select.appendChild(option);
    });

    if (tickets.length > 0) {
      hydrateFromSelected();
      setStatus(`Загружено тикетов: ${tickets.length}`);
    } else {
      setStatus('Тикеты не найдены');
    }
  } catch (error) {
    setStatus(`Ошибка загрузки тикетов: ${error.message}`);
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
    setStatus(`Ошибка: ${error.message}`);
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
    setStatus(`Ошибка: ${error.message}`);
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
    setStatus(`Ошибка: ${error.message}`);
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
    setIngestStatus(msg.includes('409') || msg.includes('уже') ? 'Письмо уже было обработано ранее.' : `Ошибка: ${msg}`);
  } finally {
    if (btn) btn.disabled = false;
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
  if (processLatestBtn) processLatestBtn.addEventListener('click', processLatestEmail);

  loadTickets();
});
