const DEFAULT_BRIDGE = 'ws://127.0.0.1:8766/extension';
let bridgeUrl = DEFAULT_BRIDGE;
let socket;
let controlledTabId = null;
let refsByTab = new Map();
let pendingPairCode = '';

async function setBadge(text, color = '#235ee7') {
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
}

function validBridgeUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'ws:' && parsed.hostname === '127.0.0.1'
      && !!parsed.port && parsed.pathname === '/extension' && !parsed.search && !parsed.hash;
  } catch { return false; }
}

function connect(code = '', requestedBridge = '') {
  if (code) pendingPairCode = code;
  if (requestedBridge && requestedBridge !== bridgeUrl) {
    if (!validBridgeUrl(requestedBridge)) {
      chrome.runtime.sendMessage({ type: 'pair-error', error: 'Atlas 本机连接地址无效' });
      return;
    }
    bridgeUrl = requestedBridge;
    void chrome.storage.local.set({ bridgeUrl });
    socket?.close();
    socket = null;
  }
  if (socket?.readyState === WebSocket.OPEN) {
    if (pendingPairCode) {
      socket.send(JSON.stringify({ type: 'pair', code: pendingPairCode }));
      pendingPairCode = '';
    }
    return;
  }
  if (socket && socket.readyState < WebSocket.CLOSING) return;
  socket = new WebSocket(bridgeUrl);
  const activeSocket = socket;
  socket.onopen = async () => {
    if (pendingPairCode) {
      socket.send(JSON.stringify({ type: 'pair', code: pendingPairCode }));
      pendingPairCode = '';
    }
    else {
      const { token } = await chrome.storage.local.get('token');
      if (token) socket.send(JSON.stringify({ type: 'auth', token }));
    }
  };
  socket.onmessage = async (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'paired') {
      if (!msg.ok) { chrome.runtime.sendMessage({ type: 'pair-error', error: msg.error }); return; }
      await chrome.storage.local.set({ token: msg.token, paired: true });
      chrome.runtime.sendMessage({ type: 'paired', ok: true });
      return;
    }
    if (msg.type === 'ready') { await chrome.storage.local.set({ paired: true }); return; }
    if (msg.type === 'command') {
      try {
        const result = await perform(msg.action, msg.args || {});
        socket.send(JSON.stringify({ id: msg.id, result }));
      } catch (error) {
        socket.send(JSON.stringify({ id: msg.id, error: String(error?.message || error) }));
      }
    }
  };
  socket.onclose = async () => {
    if (socket !== activeSocket) return;
    await chrome.storage.local.set({ paired: false });
    await setBadge('', '#b42318');
    setTimeout(() => connect(), 1500);
  };
}

async function command(method, params = {}) {
  if (controlledTabId == null) throw new Error('请先在 Atlas 扩展弹窗中选择并接管一个标签页');
  return chrome.debugger.sendCommand({ tabId: controlledTabId }, method, params);
}

async function evaluate(expression) {
  const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || '页面脚本执行失败');
  return result.result?.value;
}

async function perform(action, args) {
  if (action === 'browser_navigate') {
    await command('Page.enable');
    await command('Page.navigate', { url: String(args.url || '') });
    await new Promise((resolve) => setTimeout(resolve, 800));
    return { success: true, data: { url: await evaluate('location.href'), title: await evaluate('document.title') } };
  }
  if (action === 'browser_snapshot') {
    const snapshot = await evaluate(`(() => {
      const els = [...document.querySelectorAll('a,button,input,textarea,select,[role="button"],[role="link"]')];
      const refs = {}; let i = 1;
      const rows = els.filter(e => e.getClientRects().length).map(e => {
        const ref = '@e' + i++; const tag=e.tagName.toLowerCase(); const text=(e.innerText||e.getAttribute('aria-label')||e.placeholder||e.value||'').trim().slice(0,160);
        e.setAttribute('data-atlas-ref', ref); refs[ref]=true; return {ref,tag,text};
      }); window.__atlasRefs=refs; return {title:document.title,url:location.href,text:document.body.innerText.slice(0,12000),elements:rows};
    })()`);
    const refs = await evaluate('window.__atlasRefs || {}');
    refsByTab.set(controlledTabId, refs);
    const rows = snapshot.elements.map((e) => `${e.ref} ${e.tag}${e.text ? ` ${e.text}` : ''}`).join('\n');
    return { success: true, data: { snapshot: `${snapshot.title}\n${snapshot.url}\n${snapshot.text}\n${rows}`, refs: refs } };
  }
  if (action === 'browser_click') {
    const ref = String(args.ref || '');
    const ok = await evaluate(`(() => { const e=document.querySelector('[data-atlas-ref="${ref.replace(/[^@e0-9]/g, '')}"]'); if(!e)return false; e.click(); return true; })()`);
    if (!ok) throw new Error(`找不到元素 ${ref}，请重新获取快照`);
    return { success: true, data: {} };
  }
  if (action === 'browser_type') {
    const ref = String(args.ref || '');
    const ok = await evaluate(`(() => { const e=document.querySelector('[data-atlas-ref="${ref.replace(/[^@e0-9]/g, '')}"]'); if(!e)return false; e.focus(); if('value' in e){e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));} return true; })()`);
    if (!ok) throw new Error(`找不到元素 ${ref}`);
    await command('Input.insertText', { text: String(args.text || '') });
    return { success: true, data: {} };
  }
  if (action === 'browser_press') { await command('Input.dispatchKeyEvent', { type: 'keyDown', key: String(args.key || 'Enter') }); await command('Input.dispatchKeyEvent', { type: 'keyUp', key: String(args.key || 'Enter') }); return { success: true, data: {} }; }
  if (action === 'browser_back') { await command('Page.navigateToHistoryEntry', { entryId: -1 }).catch(() => command('Runtime.evaluate', { expression: 'history.back()' })); return { success: true, data: {} }; }
  if (action === 'browser_scroll') { await evaluate(`window.scrollBy(0, ${String(args.direction || 'down') === 'up' ? '-500' : '500'})`); return { success: true, data: {} }; }
  if (action === 'browser_vision') { const shot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }); return { success: true, data: { screenshot_base64: shot.data } }; }
  throw new Error(`扩展控制暂不支持 ${action}`);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg.type === 'pair') { connect(String(msg.code || ''), String(msg.url || '')); sendResponse({ ok: true }); }
    else if (msg.type === 'state') sendResponse({ connected: socket?.readyState === WebSocket.OPEN, tabId: controlledTabId, bridgeUrl });
    else if (msg.type === 'attach') {
      const tab = await chrome.tabs.get(Number(msg.tabId));
      if (controlledTabId != null) await chrome.debugger.detach({ tabId: controlledTabId }).catch(() => {});
      await chrome.debugger.attach({ tabId: tab.id }, '1.3');
      controlledTabId = tab.id;
      await chrome.debugger.sendCommand({ tabId: tab.id }, 'Page.enable');
      await chrome.action.setBadgeText({ text: 'ON' }); await setBadge('ON');
      await chrome.action.setTitle({ title: `Atlas 控制中：${tab.title || tab.url}` });
      sendResponse({ ok: true, tabId: tab.id, title: tab.title, url: tab.url });
    } else if (msg.type === 'detach') {
      if (controlledTabId != null) await chrome.debugger.detach({ tabId: controlledTabId }).catch(() => {});
      controlledTabId = null; refsByTab.clear(); await setBadge(''); await chrome.action.setTitle({ title: 'Atlas browser control' });
      await chrome.storage.local.remove(['token', 'paired']);
      socket?.close();
      sendResponse({ ok: true });
    }
  })().catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
  return true;
});

chrome.debugger.onDetach.addListener(({ tabId }) => {
  if (controlledTabId === tabId) {
    controlledTabId = null;
    refsByTab.clear();
    void setBadge('');
    void chrome.action.setTitle({ title: 'Atlas browser control' });
  }
});

chrome.storage.local.get('bridgeUrl').then(({ bridgeUrl: saved }) => {
  if (typeof saved === 'string' && validBridgeUrl(saved)) bridgeUrl = saved;
  connect();
});
setInterval(() => { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' })); }, 12000);
