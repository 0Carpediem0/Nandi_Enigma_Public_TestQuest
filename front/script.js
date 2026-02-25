const API_URL = 'http://localhost:8000/tickets';

async function fetchTickets() {
  try {
    const response = await fetch(API_URL);
    
    if (!response.ok) throw new Error('Нет соединения с API');
    
    const data = await response.json();
    renderTable(data);
  } catch (error) {
    console.warn('Бэкенд не найден, используем тестовые данные:', error);
    const mockData = getMockData();
    renderTable(mockData);
  }
}

function renderTable(tickets) {
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = ''; 

  tickets.forEach(ticket => {
    const row = document.createElement('tr');

    row.innerHTML = `
      <td>${formatDate(ticket.date)}</td>
      <td>${ticket.full_name}</td>
      <td>${ticket.object}</td>
      <td>${ticket.phone}</td>
      <td>${ticket.email}</td>
      <td>${ticket.serial_numbers}</td>
      <td>${ticket.device_type}</td>
      <td><span class="badge badge-${getToneClass(ticket.emotional_tone)}">${ticket.emotional_tone}</span></td>
      <td class="question-cell">${ticket.question}</td>
    `;
    
    tbody.appendChild(row);
  });
}

// Тестовые данные
function getMockData() {
  return [
    {
      date: "2026-02-25T12:24:00",
      full_name: "Иванов Иван Иванович",
      object: "Завод №5",
      phone: "+7 (999) 123-45-67",
      email: "ivanov@zavod5.ru",
      serial_numbers: "GA-12345, GA-12346",
      device_type: "Газоанализатор ГАНК-4",
      emotional_tone: "Негатив",
      question: "Не включается насос..."
    },
    {
      date: "2026-02-25T14:44:00",
      full_name: "Петрова Мария Сергеевна",
      object: "Цех обработки",
      phone: "+7 (999) 765-43-21",
      email: "petrova@zavod5.ru",
      serial_numbers: "GA-78901",
      device_type: "Датчик давления ДД-100",
      emotional_tone: "Нейтраль",
      question: "Как починить прибор?"
    }
  ];
}

function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleString('ru-RU', { 
    day: '2-digit', month: '2-digit', year: 'numeric', 
    hour: '2-digit', minute: '2-digit' 
  });
}

function getToneClass(tone) {
  if (tone.toLowerCase().includes('негатив')) return 'negative';
  if (tone.toLowerCase().includes('позитив')) return 'positive';
  return 'neutral';
}

document.addEventListener('DOMContentLoaded', fetchTickets);



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
      if (index < 9) {
        rowData.push(cell.textContent);
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
    { wch: 40 }  // Суть вопроса
  ];
  
  XLSX.utils.book_append_sheet(wb, ws, 'Заявки');

  const date = new Date().toLocaleDateString('ru-RU').replace(/\./g, '-');
  const filename = `zayavki_${date}.xlsx`;
  
  XLSX.writeFile(wb, filename);
}