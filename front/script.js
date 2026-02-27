const API_BASE = 'http://localhost:8000';
const API_TICKETS = `${API_BASE}/tickets`;

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || 'Ошибка API');
  }
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  return response.text();
}

async function fetchTickets() {
  try {
    const data = await apiFetch(API_TICKETS);
    renderTable(data);
  } catch (error) {
    console.warn('Бэкенд недоступен, используем тестовые данные:', error);
    renderTable(getMockData());
  }
}

function renderTable(tickets) {
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = '';

  tickets.forEach(ticket => {
    const row = document.createElement('tr');
    const normalizedTone = normalizeTone(ticket.emotional_tone);
    const questionText = String(ticket.question || '-');
    const aiResponseText = String(ticket.ai_response || '-');

    row.dataset.ticketId = String(ticket.id || '');
    row.dataset.question = questionText;
    row.dataset.aiResponse = aiResponseText;
    row.dataset.status = String(ticket.status || 'new');
    row.dataset.email = String(ticket.email || '');

    row.innerHTML = `
      <td>${formatDate(ticket.date)}</td>
      <td>${escapeHtml(ticket.full_name || '-')}</td>
      <td>${escapeHtml(ticket.object || '-')}</td>
      <td>${escapeHtml(ticket.phone || '-')}</td>
      <td>${escapeHtml(ticket.email || '-')}</td>
      <td>${escapeHtml(ticket.serial_numbers || '-')}</td>
      <td>${escapeHtml(ticket.device_type || '-')}</td>
      <td><span class="badge badge-${getToneClass(normalizedTone)}">${normalizedTone}</span></td>
      <td class="expandable-cell">${buildPreviewCell(questionText)}</td>
      <td class="expandable-cell">${buildPreviewCell(aiResponseText)}</td>
    `;

    tbody.appendChild(row);
  });
}

function getMockData() {
  return [
    {
      id: 1,
      date: '2026-02-25T12:24:00',
      full_name: 'Иванов Иван Иванович',
      object: 'Завод №5',
      phone: '+7 (999) 123-45-67',
      email: 'ivanov@zavod5.ru',
      serial_numbers: 'GA-12345, GA-12346',
      device_type: 'Газоанализатор ГАНК-4',
      emotional_tone: 'Негативный',
      status: 'new',
      question: 'Не включается насос...',
      ai_response: 'Проверьте питание, предохранитель и выполните перезапуск контроллера.',
    },
  ];
}

function formatDate(dateString) {
  if (!dateString) return '-';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getToneClass(tone) {
  const toneValue = String(tone || '').toLowerCase();
  if (toneValue.includes('негатив')) return 'negative';
  if (toneValue.includes('позитив')) return 'positive';
  return 'neutral';
}

function normalizeTone(tone) {
  const toneValue = String(tone || '').toLowerCase();
  if (toneValue.includes('негатив')) return 'Негативный';
  if (toneValue.includes('позитив')) return 'Позитивный';
  return 'Нейтральный';
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function buildPreviewCell(value) {
  const text = escapeHtml(getShortPreview(value, 55));
  return `
    <div class="expandable-content">
      <span class="cell-text">${text}</span>
      <button type="button" class="toggle-cell-btn open-popup-btn">Показать</button>
    </div>
  `;
}

function getShortPreview(value, maxLength = 55) {
  const text = String(value || '-').trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}

function setupPopup() {
  const modal = document.getElementById('detailsModal');
  const closeButton = document.getElementById('closeDetailsModal');
  const questionNode = document.getElementById('modalQuestionText');
  const aiNode = document.getElementById('modalAiText');
  const tbody = document.getElementById('tableBody');

  if (!modal || !closeButton || !questionNode || !aiNode || !tbody) return;

  const closeModal = () => {
    modal.classList.remove('is-open');
    document.body.classList.remove('modal-open');
  };

  const openModal = (row) => {
    questionNode.textContent = row.dataset.question || '-';
    aiNode.textContent = row.dataset.aiResponse || '-';
    modal.classList.add('is-open');
    document.body.classList.add('modal-open');
  };

  tbody.addEventListener('click', (event) => {
    const button = event.target.closest('.open-popup-btn');
    if (!button) return;
    const row = button.closest('tr');
    if (!row) return;
    openModal(row);
  });

  closeButton.addEventListener('click', closeModal);
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-open')) {
      closeModal();
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setupPopup();
  fetchTickets();
});

function exportTableToExcel() {
  const tbody = document.getElementById('tableBody');
  const rows = tbody.querySelectorAll('tr');

  const data = [];

  const headers = [];
  document.querySelectorAll('.data-table th').forEach(th => {
    headers.push(th.textContent);
  });
  data.push(headers);

  rows.forEach(row => {
    const rowData = [];
    row.querySelectorAll('td').forEach((cell, index) => {
      if (index < 10) {
        if (index === 8) {
          rowData.push((row.dataset.question || '-').trim());
          return;
        }
        if (index === 9) {
          rowData.push((row.dataset.aiResponse || '-').trim());
          return;
        }
        rowData.push(cell.textContent.trim());
      }
    });
    if (rowData.length > 0) {
      data.push(rowData);
    }
  });

  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(data);

  ws['!cols'] = [
    { wch: 20 }, // Дата
    { wch: 30 }, // ФИО
    { wch: 25 }, // Объект
    { wch: 20 }, // Телефон
    { wch: 30 }, // Email
    { wch: 25 }, // Заводские номера
    { wch: 25 }, // Тип приборов
    { wch: 15 }, // Эмоциональный окрас
    { wch: 40 }, // Суть вопроса
    { wch: 50 }  // Ответ AI
  ];
  
  XLSX.utils.book_append_sheet(wb, ws, 'Заявки');

  const date = new Date().toLocaleDateString('ru-RU').replace(/\./g, '-');
  const filename = `zayavki_${date}.xlsx`;
  
  XLSX.writeFile(wb, filename);
}