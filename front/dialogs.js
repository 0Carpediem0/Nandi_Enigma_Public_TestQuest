(function () {
  var API_BASE = 'http://localhost:8000';
  var API_DIALOGS = API_BASE + '/dialogs';
  var API_DIALOG_MESSAGES = function (id) { return API_BASE + '/dialogs/' + id + '/messages'; };

  async function apiFetch(url, options) {
    var response = await fetch(url, options);
    if (!response.ok) {
      var text = await response.text();
      throw new Error(text || 'Ошибка API');
    }
    var contentType = response.headers.get('content-type') || '';
    if (contentType.indexOf('application/json') !== -1) return response.json();
    return response.text();
  }

  async function fetchDialogs() {
    try {
      var data = await apiFetch(API_DIALOGS);
      return Array.isArray(data) ? data : [];
    } catch (e) {
      console.warn('Бэкенд диалогов недоступен, используем тестовые данные:', e);
      Object.assign(chats, getMockMessages());
      return getMockDialogs();
    }
  }

  async function fetchDialogMessages(dialogId) {
    try {
      var data = await apiFetch(API_DIALOG_MESSAGES(dialogId));
      return Array.isArray(data) ? data : [];
    } catch (e) {
      console.warn('Не удалось загрузить сообщения диалога:', e);
      return [];
    }
  }

  function getMockDialogs() {
    return [
      { id: '1', contact: 'X@sup.ru', last_message_text: 'Не включается насос...', last_message_time: '2026-03-01T12:24:00', status: 'ai' },
      { id: '2', contact: 'Z@sup.ru', last_message_text: 'Ошибка датчика...', last_message_time: '2026-03-01T12:44:00', status: 'process' },
      { id: '3', contact: 'Y@sup.ru', last_message_text: 'Срочно нужна консультация...', last_message_time: '2026-03-01T20:31:00', status: 'operator' }
    ];
  }

  function getStatusLabel(status) {
    if (status === 'ai') return 'обработано AI';
    if (status === 'process') return 'в процессе';
    if (status === 'operator') return 'нужна помощь оператора';
    return '—';
  }

  function getStatusClass(status) {
    if (status === 'ai') return 'dialogs_status_ai';
    if (status === 'process') return 'dialogs_status_process';
    if (status === 'operator') return 'dialogs_status_operator';
    return 'dialogs_status_ai';
  }

 
  function getMockMessages() {
    return {
      'X@sup.ru': [
        { text: 'Добрый день, не включается насос после перезагрузки.', outgoing: false, meta: 'AI', time: new Date('2026-03-01T12:24:00') },
        { text: 'Проверьте питание и предохранитель, выполните перезапуск контроллера.', outgoing: true, meta: 'AI', time: new Date('2026-03-01T12:25:00') },
        { text: 'Не помогло, ошибка на экране 0x12.', outgoing: false, meta: 'help', time: new Date('2026-03-01T12:26:00') }
      ],
      'Z@sup.ru': [
        { text: 'Здравствуйте, постоянно срабатывает ошибка датчика давления.', outgoing: false, meta: 'AI', time: new Date('2026-03-01T12:44:00') },
        { text: 'Выполните калибровку по инструкции, раздел 4.2. Если ошибка повторится — пришлите фото экрана.', outgoing: true, meta: 'AI', time: new Date('2026-03-01T12:45:00') }
      ],
      'Y@sup.ru': [
        { text: 'Срочно нужна консультация по настройке системы.', outgoing: false, meta: null, time: new Date('2026-03-01T20:31:00') }
      ]
    };
  }

  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function formatTime(date) {
    if (!date) return '—';
    var d = date instanceof Date ? date : new Date(date);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  }

  function getShortPreview(msg, maxLen) {
    maxLen = maxLen || 40;
    var t = (msg && msg.text) ? String(msg.text).trim() : '';
    if (msg && msg.fileName) t = (t ? t + ' ' : '') + '📎 ' + msg.fileName;
    if (!t) return 'Нет сообщений';
    if (t.length <= maxLen) return t;
    return t.slice(0, maxLen) + '...';
  }

  function normalizeMessage(m) {
    var time = m.created_at ? new Date(m.created_at) : (m.time || new Date());
    return {
      text: m.text || '',
      outgoing: Boolean(m.outgoing),
      meta: m.meta || null,
      time: time,
      fileName: m.file_name || m.fileName || null
    };
  }

  var chats = {};
  var dialogsFromBackend = [];
  var contactToId = {};

  var currentUser = null;
  var attachedFile = null;
  var attachedFileName = '';

  var dialogsList = document.getElementById('dialogsList');
  var dialogsSearch = document.getElementById('dialogsSearch');
  var chatUsername = document.getElementById('chatUsername');
  var chatAvatarLetter = document.getElementById('chatAvatarLetter');
  var chatMessages = document.getElementById('chatMessages');
  var chatInput = document.getElementById('chatInput');
  var sendMsgBtn = document.getElementById('sendMsgBtn');
  var exportChatBtn = document.getElementById('exportChatBtn');
  var dialogsFileInput = document.getElementById('dialogsFileInput');
  var attachmentPreview = document.getElementById('attachmentPreview');
  var dialogsAttachBtn = document.getElementById('dialogsAttachBtn');
  var dialogsEmojiBtn = document.getElementById('dialogsEmojiBtn');
  var emojiPicker = document.getElementById('emojiPicker');

  function renderDialogsList(dialogs) {
    dialogsFromBackend = dialogs || [];
    contactToId = {};
    dialogsFromBackend.forEach(function (d) {
      contactToId[d.contact] = d.id;
    });
    if (!dialogsList) return;
    dialogsList.innerHTML = '';
    dialogs.forEach(function (d, index) {
      var contact = d.contact || ('contact_' + d.id);
      var letter = (contact && contact[0]) ? contact[0].toUpperCase() : '?';
      var lastTime = d.last_message_time ? formatTime(d.last_message_time) : '—';
      var preview = (d.last_message_text || 'Нет сообщений').slice(0, 40);
      if ((d.last_message_text || '').length > 40) preview += '...';
      var statusClass = getStatusClass(d.status);
      var statusLabel = getStatusLabel(d.status);
      var li = document.createElement('li');
      li.className = 'dialogs_item' + (index === 0 ? ' dialogs_item_active' : '');
      li.dataset.user = contact;
      li.dataset.dialogId = String(d.id);
      li.innerHTML = '<div class="dialogs_item_avatar"><span class="dialogs_avatar_placeholder">' + escapeHtml(letter) + '</span></div>' +
        '<div class="dialogs_item_content">' +
        '<div class="dialogs_item_row"><span class="dialogs_item_user">' + escapeHtml(contact) + '</span><span class="dialogs_item_time">' + escapeHtml(lastTime) + '</span></div>' +
        '<p class="dialogs_item_preview">' + escapeHtml(preview) + '</p>' +
        '<div class="dialogs_item_status ' + statusClass + '"><span class="dialogs_status_dot"></span><span>' + escapeHtml(statusLabel) + '</span></div>' +
        '</div>';
      dialogsList.appendChild(li);
    });
    if (dialogs.length > 0) {
      var first = dialogs[0];
      currentUser = first.contact;
      if (chats[currentUser]) {
        setCurrentDialog(currentUser);
      } else if (first.id) {
        fetchDialogMessages(first.id).then(function (msgs) {
          chats[currentUser] = msgs.map(normalizeMessage);
          setCurrentDialog(currentUser);
          updateSidebarPreviews();
        });
      } else {
        setCurrentDialog(currentUser);
      }
    }
    updateSidebarPreviews();
  }

  function filterDialogsByContact() {
    var query = (dialogsSearch && dialogsSearch.value || '').trim().toLowerCase();
    if (!dialogsList) return;
    dialogsList.querySelectorAll('.dialogs_item').forEach(function (item) {
      var contact = (item.dataset.user || '').toLowerCase();
      var show = !query || contact.indexOf(query) !== -1;
      item.style.display = show ? '' : 'none';
    });
  }

  if (dialogsSearch) {
    dialogsSearch.addEventListener('input', filterDialogsByContact);
    dialogsSearch.addEventListener('search', filterDialogsByContact);
  }

  function renderChat(user) {
    if (!chatMessages) return;
    var list = chats[user] || [];
    chatMessages.innerHTML = '';
    list.forEach(function (msg) {
      var wrap = document.createElement('div');
      wrap.className = 'dialogs_msg ' + (msg.outgoing ? 'dialogs_msg_outgoing' : 'dialogs_msg_incoming');
      var metaClass = msg.meta === 'help' ? ' help' : '';
      var metaHtml = msg.meta ? '<span class="dialogs_msg_meta' + metaClass + '">' + escapeHtml(msg.meta) + '</span>' : '';
      var body = '<p>' + escapeHtml(msg.text || '') + '</p>';
      if (msg.fileName) {
        body += '<div class="dialogs_msg_attachment">📎 ' + escapeHtml(msg.fileName) + '</div>';
      }
      wrap.innerHTML = '<div class="dialogs_msg_bubble">' + body + metaHtml + '</div>';
      chatMessages.appendChild(wrap);
    });
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function updateSidebarPreviews() {
    if (!dialogsList) return;
    dialogsList.querySelectorAll('.dialogs_item').forEach(function (el) {
      var user = el.dataset.user;
      var list = chats[user] || [];
      var last = list[list.length - 1];
      var previewEl = el.querySelector('.dialogs_item_preview');
      var timeEl = el.querySelector('.dialogs_item_time');
      if (previewEl) {
        previewEl.textContent = last ? getShortPreview(last, 40) : 'Нет сообщений';
      }
      if (timeEl && last && last.time) {
        timeEl.textContent = formatTime(last.time);
      }
    });
  }

  function setCurrentDialog(user) {
    currentUser = user;
    if (chatUsername) chatUsername.textContent = user || '';
    if (chatAvatarLetter) chatAvatarLetter.textContent = (user && user[0]) ? user[0].toUpperCase() : '?';
    renderChat(user);
  }

  if (dialogsList) {
    dialogsList.addEventListener('click', function (e) {
      var item = e.target.closest('.dialogs_item');
      if (!item) return;
      var contact = item.dataset.user || '';
      var dialogId = item.dataset.dialogId;
      dialogsList.querySelectorAll('.dialogs_item').forEach(function (el) {
        el.classList.remove('dialogs_item_active');
      });
      item.classList.add('dialogs_item_active');
      if (!chats[contact] && dialogId) {
        fetchDialogMessages(dialogId).then(function (msgs) {
          chats[contact] = msgs.map(normalizeMessage);
          setCurrentDialog(contact);
          updateSidebarPreviews();
        });
      } else {
        setCurrentDialog(contact);
      }
    });
  }

  function clearAttachment() {
    attachedFile = null;
    attachedFileName = '';
    if (dialogsFileInput) dialogsFileInput.value = '';
    if (attachmentPreview) {
      attachmentPreview.classList.remove('is-visible');
      attachmentPreview.innerHTML = '';
    }
  }

  function sendMessage() {
    var text = chatInput ? chatInput.value.trim() : '';
    if (!text && !attachedFile) return;
    if (!chatMessages) return;
    if (!chats[currentUser]) chats[currentUser] = [];
    var now = new Date();
    var payload = {
      text: text || '(файл)',
      outgoing: true,
      meta: null,
      time: now
    };
    if (attachedFileName) payload.fileName = attachedFileName;
    chats[currentUser].push(payload);
    renderChat(currentUser);
    updateSidebarPreviews();
    chatInput.value = '';
    clearAttachment();
  }

  if (sendMsgBtn && chatInput) {
    sendMsgBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  if (dialogsAttachBtn && dialogsFileInput) {
    dialogsAttachBtn.addEventListener('click', function () {
      dialogsFileInput.click();
    });
  }

  if (dialogsFileInput && attachmentPreview) {
    dialogsFileInput.addEventListener('change', function () {
      var file = dialogsFileInput.files && dialogsFileInput.files[0];
      if (!file) return;
      attachedFile = file;
      attachedFileName = file.name;
      attachmentPreview.innerHTML = '<span class="dialogs_attachment_name" title="' + escapeHtml(file.name) + '">📎 ' + escapeHtml(file.name) + '</span>' +
        '<button type="button" class="dialogs_attachment_remove" aria-label="Удалить вложение">×</button>';
      attachmentPreview.classList.add('is-visible');
      attachmentPreview.querySelector('.dialogs_attachment_remove').addEventListener('click', function (e) {
        e.preventDefault();
        clearAttachment();
      });
    });
  }

  var EMOJIS = ['😀','😃','😄','😁','😅','😂','🤣','😊','😇','🙂','😉','😌','😍','🥰','😘','😗','😙','😚','🙄','😋','😛','😜','🤪','😝','🤑','🤗','🤭','🤫','🤔','🤐','😐','😑','😶','😏','😒','🙄','😬','🤥','😌','😔','😪','🤤','😴','😷','🤒','🤕','🤢','🤮','😵','🤯','🤠','🥳','🥺','😎','🤓','🧐','😕','😟','🙁','☹️','😮','😯','😲','😳','🥺','😦','😧','😨','😰','😥','😢','😭','😱','👍','👎','👌','✌️','🤞','🤟','🤘','👋','🤚','🖐️','✋','🖖','👏','🙌','🤲','🤝','🙏'];
  if (emojiPicker) {
    EMOJIS.forEach(function (emoji) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = emoji;
      btn.setAttribute('aria-label', 'Вставить ' + emoji);
      btn.addEventListener('click', function () {
        if (!chatInput) return;
        var start = chatInput.selectionStart;
        var end = chatInput.selectionEnd;
        var val = chatInput.value;
        chatInput.value = val.slice(0, start) + emoji + val.slice(end);
        chatInput.selectionStart = chatInput.selectionEnd = start + emoji.length;
        chatInput.focus();
        emojiPicker.classList.remove('is-open');
      });
      emojiPicker.appendChild(btn);
    });
  }

  if (dialogsEmojiBtn && emojiPicker) {
    dialogsEmojiBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      emojiPicker.classList.toggle('is-open');
    });
  }

  document.addEventListener('click', function (e) {
    if (emojiPicker && emojiPicker.classList.contains('is-open') &&
        !emojiPicker.contains(e.target) && e.target !== dialogsEmojiBtn) {
      emojiPicker.classList.remove('is-open');
    }
  });

  if (exportChatBtn) {
    exportChatBtn.addEventListener('click', function () {
      if (typeof XLSX === 'undefined') {
        alert('Библиотека экспорта не загружена. Проверьте подключение скрипта XLSX.');
        return;
      }
      var list = chats[currentUser] || [];
      var rows = [['Сообщение']];
      list.forEach(function (m) {
        var text = (m.text || '') + (m.fileName ? ' 📎 ' + m.fileName : '');
        rows.push([text]);
      });
      if (rows.length === 1) rows.push(['Нет сообщений']);
      var ws = XLSX.utils.aoa_to_sheet(rows);
      var wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Чат');
      var safeName = (currentUser || 'chat').replace(/[^a-zA-Z0-9@._-]/g, '_').slice(0, 30);
      var dateStr = new Date().toLocaleDateString('ru-RU').replace(/\./g, '-');
      var fileName = 'chat_' + safeName + '_' + dateStr + '.xlsx';
      XLSX.writeFile(wb, fileName);
    });
  }

  fetchDialogs().then(function (dialogs) {
    renderDialogsList(dialogs);
  });
})();
