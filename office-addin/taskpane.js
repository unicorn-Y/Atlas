(() => {
  const TOKEN_KEY = 'atlas.office.session-token.v1';
  const pairing = document.querySelector('#pairing');
  const connected = document.querySelector('#connected');
  const connection = document.querySelector('#connection');
  const pairCode = document.querySelector('#pairCode');
  const pairMessage = document.querySelector('#pairMessage');
  const selection = document.querySelector('#selection');
  const documentInfo = document.querySelector('#documentInfo');
  const selectionMessage = document.querySelector('#selectionMessage');
  const writebacks = document.querySelector('#writebacks');
  const pendingCount = document.querySelector('#pendingCount');
  const liveControlButton = document.querySelector('#liveControlButton');
  const liveStatus = document.querySelector('#liveStatus');
  let officeHost = '';
  let documentName = '';
  let documentAddress = '';
  let pollTimer = 0;
  let liveTimer = 0;
  let liveControl = false;
  const pending = [];

  async function api(path, options = {}) {
    const token = localStorage.getItem(TOKEN_KEY);
    const headers = { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { 'X-Atlas-Office-Token': token } : {}), ...(options.headers || {}) };
    const response = await fetch(path, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Atlas 返回 ${response.status}`);
    return body;
  }

  function showConnected(value) {
    pairing.classList.toggle('hidden', value);
    connected.classList.toggle('hidden', !value);
    connection.textContent = value ? '已配对' : '未配对';
    connection.style.color = value ? '#26764e' : '#666';
    if (value) startPolling(); else stopPolling();
  }

  function setError(target, error) {
    target.textContent = error instanceof Error ? error.message : String(error);
  }

  async function pair() {
    const code = pairCode.value.trim();
    if (!/^\d{8}$/.test(code)) { pairMessage.textContent = '请输入 8 位数字配对码。'; return; }
    document.querySelector('#pairButton').disabled = true;
    pairMessage.textContent = '正在连接…';
    try {
      const result = await api('/api/office/pair', { method: 'POST', body: JSON.stringify({ pairing_code: code }) });
      localStorage.setItem(TOKEN_KEY, result.session_token);
      pairMessage.textContent = '';
      await refreshDocumentInfo();
      showConnected(true);
    } catch (error) { setError(pairMessage, error); }
    finally { document.querySelector('#pairButton').disabled = false; }
  }

  async function getSelection() {
    if (!window.Office || !Office.context) throw new Error('请从 Word 或 PowerPoint 桌面加载项中打开本面板。');
    if (officeHost === 'Excel' && window.Excel?.run) {
      return Excel.run(async (context) => {
        const range = context.workbook.getSelectedRange();
        range.load(['address', 'text']);
        await context.sync();
        return { text: range.text.map((row) => row.join('\t')).join('\n'), address: range.address };
      });
    }
    return new Promise((resolve, reject) => Office.context.document.getSelectedDataAsync(Office.CoercionType.Text, (result) => {
      if (result.status === Office.AsyncResultStatus.Succeeded) resolve({ text: String(result.value || ''), address: '当前选区' });
      else reject(new Error(result.error?.message || '无法读取当前选区'));
    }));
  }

  async function refreshSelection() {
    selectionMessage.textContent = '正在读取选区…';
    try {
      const result = await getSelection();
      selection.value = result.text;
      documentAddress = result.address;
      selectionMessage.textContent = result.text.trim() ? `已读取 ${result.text.length.toLocaleString()} 个字符。` : '当前没有选中文本或非空单元格。';
    } catch (error) { setError(selectionMessage, error); }
  }

  async function sendSelection() {
    const text = selection.value;
    if (!text.trim()) { selectionMessage.textContent = '请先选中 Word 内容或 Excel 单元格，再刷新选区。'; return; }
    if (text.length > 50_000) { selectionMessage.textContent = '选区超过 50,000 个字符；请缩小选区后重试。'; return; }
    selectionMessage.textContent = '正在发送到 Atlas…';
    try {
      await api('/api/office/context', { method: 'POST', body: JSON.stringify({ host: officeHost, document_name: documentName, address: documentAddress, selection: text }) });
      selectionMessage.textContent = '已送入配对的 Atlas 会话草稿；请在 Atlas 检查并发送。';
    } catch (error) { setError(selectionMessage, error); }
  }

  async function refreshDocumentInfo() {
    if (!window.Office?.context) return;
    officeHost = Office.context.host === Office.HostType.Word ? 'Word' : Office.context.host === Office.HostType.PowerPoint ? 'PowerPoint' : Office.context.host === Office.HostType.Excel ? 'Excel' : String(Office.context.host || 'Office');
    const url = Office.context.document.url || '';
    try { documentName = url ? decodeURIComponent(new URL(url).pathname.split('/').pop() || '') : ''; } catch { documentName = ''; }
    documentInfo.textContent = `${officeHost}${documentName ? ` · ${documentName}` : ' · 未命名文档'}`;
  }

  async function hashText(text) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
  }

  async function syncLiveControl() {
    if (!liveControl) return;
    try {
      const snapshot = await getSelection();
      if (!snapshot.text.trim()) return;
      const result = await api('/api/office/live/sync', { method: 'POST', body: JSON.stringify({ content: snapshot.text, address: snapshot.address }) });
      liveStatus.textContent = `实时控制中 · ${documentName || officeHost} · 同步于 ${new Date(result.updated_at * 1000).toLocaleTimeString()}`;
    } catch (error) { setError(liveStatus, error); }
  }

  async function toggleLiveControl() {
    liveControlButton.disabled = true;
    try {
      if (liveControl) {
        await api('/api/office/live/stop', { method: 'POST' });
        liveControl = false; clearInterval(liveTimer); liveTimer = 0;
        liveStatus.textContent = '实时控制已停止'; liveControlButton.textContent = '开始实时控制'; return;
      }
      const snapshot = await getSelection();
      if (!snapshot.text.trim()) throw new Error('请先在 Word/PowerPoint 中选中要实时控制的文字。');
      await api('/api/office/live/start', { method: 'POST', body: JSON.stringify({ host: officeHost, document_name: documentName, address: snapshot.address, content: snapshot.text }) });
      liveControl = true; liveControlButton.textContent = '停止实时控制';
      liveStatus.textContent = '实时控制已启动；正在同步活动选区。';
      liveTimer = window.setInterval(() => void syncLiveControl(), 1800);
    } catch (error) { setError(liveStatus, error); }
    finally { liveControlButton.disabled = false; }
  }

  function renderWritebacks() {
    pendingCount.textContent = String(pending.length);
    if (!pending.length) { writebacks.innerHTML = '<p class="empty">尚无待写回内容。</p>'; return; }
    writebacks.replaceChildren(...pending.map((item) => {
      const card = document.createElement('article'); card.className = 'writeback';
      const preview = document.createElement('pre'); preview.textContent = item.text;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = item.conflict ? '版本冲突：仍然覆盖当前选区' : '写入当前选区';
      button.addEventListener('click', () => void writeback(item, button));
      const keep = document.createElement('button'); keep.type = 'button'; keep.textContent = '保留 Office 当前版本'; keep.className = 'secondary';
      keep.addEventListener('click', () => { const index = pending.findIndex((row) => row.id === item.id); if (index >= 0) pending.splice(index, 1); renderWritebacks(); });
      card.append(preview, button, keep); return card;
    }));
  }

  function setSelectedData(text) {
    return new Promise((resolve, reject) => Office.context.document.setSelectedDataAsync(text, { coercionType: Office.CoercionType.Text }, (result) => {
      if (result.status === Office.AsyncResultStatus.Succeeded) resolve();
      else reject(new Error(result.error?.message || '无法写入 Office 当前选区'));
    }));
  }

  async function writeback(item, button) {
    button.disabled = true;
    try {
      if (item.base_revision && !item.conflict) {
        const current = await getSelection();
        if (await hashText(current.text) !== item.base_revision) {
          item.conflict = true; button.disabled = false; renderWritebacks();
          liveStatus.textContent = '检测到 Office 文档在 Atlas 修改后发生变化。请选择覆盖或保留 Office 版本。';
          return;
        }
      }
      await setSelectedData(item.text);
      const index = pending.findIndex((row) => row.id === item.id);
      if (index >= 0) pending.splice(index, 1);
      renderWritebacks();
    } catch (error) { button.disabled = false; button.textContent = error instanceof Error ? error.message : String(error); }
  }

  async function poll() {
    if (!localStorage.getItem(TOKEN_KEY)) return;
    try {
      const result = await api('/api/office/writebacks/next');
      if (result.writeback && !pending.some((item) => item.id === result.writeback.id)) {
        pending.unshift(result.writeback); renderWritebacks();
      }
    } catch (error) {
      if (error instanceof Error && /expired|not paired/i.test(error.message)) {
        localStorage.removeItem(TOKEN_KEY); showConnected(false); pairMessage.textContent = error.message;
      }
    }
  }

  function startPolling() { stopPolling(); void poll(); pollTimer = window.setInterval(() => void poll(), 1500); }
  function stopPolling() { if (pollTimer) window.clearInterval(pollTimer); if (liveTimer) window.clearInterval(liveTimer); pollTimer = 0; liveTimer = 0; liveControl = false; }

  async function restorePairing() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return showConnected(false);
    try {
      await api('/api/office/status'); await refreshDocumentInfo(); showConnected(true);
      const live = await api('/api/office/live/status');
      if (live.session?.state === 'live') {
        liveControl = true; liveControlButton.textContent = '停止实时控制';
        liveStatus.textContent = `已恢复实时控制 · ${live.session.document_name || officeHost}`;
        liveTimer = window.setInterval(() => void syncLiveControl(), 1800);
      }
    }
    catch { localStorage.removeItem(TOKEN_KEY); showConnected(false); }
  }

  document.querySelector('#pairButton').addEventListener('click', () => void pair());
  pairCode.addEventListener('keydown', (event) => { if (event.key === 'Enter') void pair(); });
  document.querySelector('#refreshSelection').addEventListener('click', () => void refreshSelection());
  document.querySelector('#sendSelection').addEventListener('click', () => void sendSelection());
  liveControlButton.addEventListener('click', () => void toggleLiveControl());
  document.querySelector('#unpairButton').addEventListener('click', async () => {
    try { await api('/api/office/pair', { method: 'DELETE' }); } catch { /* local token is removed even if Atlas is offline */ }
    localStorage.removeItem(TOKEN_KEY); showConnected(false); pairMessage.textContent = '已在此 Office 配置文件断开配对。';
  });

  if (window.Office?.onReady) {
    Office.onReady(async (info) => {
      if (info.host === Office.HostType.Word || info.host === Office.HostType.Excel) {
        officeHost = info.host === Office.HostType.Word ? 'Word' : 'Excel';
        await refreshDocumentInfo(); await restorePairing();
      } else {
        connection.textContent = '等待 Word/Excel';
        pairMessage.textContent = '请从 Word 或 Excel 中打开 Atlas 加载项。';
      }
    });
  } else {
    connection.textContent = 'Office.js 未加载';
    pairMessage.textContent = 'Office.js 未连接；请在 Word/Excel 桌面应用的加载项窗格中打开。';
  }
})();
