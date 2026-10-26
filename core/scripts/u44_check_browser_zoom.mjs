// Exercise the already-running Atlas webview through CDP; do not launch another app window.
const targets = await (await fetch('http://127.0.0.1:9336/json/list')).json();
const target = targets.find((item) => item.type === 'page' && item.url.startsWith('http://127.0.0.1:5173'));
if (!target) throw new Error('Atlas CDP page is unavailable on port 9336');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let nextId = 0;
const pending = new Map();
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  const resolve = pending.get(message.id);
  if (resolve) { pending.delete(message.id); resolve(message); }
};
const cdp = (method, params = {}) => new Promise((resolve) => {
  const id = ++nextId;
  pending.set(id, resolve);
  socket.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const message = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (message.error) throw new Error(message.error.message);
  const result = message.result?.result;
  if (result?.subtype === 'error') throw new Error(result.description || 'Atlas UI evaluation failed');
  return result?.value;
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const clickButton = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
const typeAddress = async (url) => {
  await evaluate(`(()=>{const x=document.querySelector('input[aria-label="地址"]');if(!x)throw Error('Browser address bar is missing');x.focus();const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(x,${JSON.stringify(url)});x.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:${JSON.stringify(url)}}));x.closest('form').requestSubmit();return true})()`);
};
const waitFor = async (predicate, label) => {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (await evaluate(predicate)) return;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${label}`);
};
const activeZoom = `(()=>[...document.querySelectorAll('webview')].find(v=>v.parentElement?.parentElement?.getAttribute('aria-hidden')==='false')?.getZoomFactor?.()??1)()`;

try {
  // Pick a clean, existing conversation; creating the panel does not send a message.
  const hasConversation = await evaluate(`Boolean(document.querySelector('[aria-label="切换任务面板"]'))`);
  if (!hasConversation) {
    await clickButton('button[aria-label="新建对话"]');
    await waitFor(`Boolean(document.querySelector('[aria-label="切换任务面板"]'))`, 'a new Atlas conversation');
  }
  const panelOpen = await evaluate(`document.querySelector('button[aria-label="切换任务面板"]')?.getAttribute('aria-pressed')==='true'`);
  if (!panelOpen) await clickButton('button[aria-label="切换任务面板"]');
  await waitFor(`Boolean([...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='浏览器'))`, 'Inspector browser tab');
  await evaluate(`([...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='浏览器'))?.click()`);
  await waitFor(`Boolean(document.querySelector('input[aria-label="地址"]'))`, 'browser address bar');
  await typeAddress('http://127.0.0.1:5173/');
  await waitFor(`Boolean(document.querySelector('webview')?.getURL?.().startsWith('http://127.0.0.1:5173'))`, 'webview navigation');

  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: '+', code: 'Equal', modifiers: 2, windowsVirtualKeyCode: 187 });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: '+', code: 'Equal', modifiers: 2, windowsVirtualKeyCode: 187 });
  await waitFor(`Math.abs((document.querySelector('webview')?.getZoomFactor?.()||1)-1.1)<0.01`, 'Ctrl+plus zoom');
  const keyboardBanner = await evaluate(`document.querySelector('[aria-label="网页缩放"]')?.innerText`);
  if (!String(keyboardBanner).includes('110%')) throw new Error(`Zoom banner did not show 110%: ${keyboardBanner}`);

  const firstTabId = await evaluate(`document.querySelector('[role="tablist"][aria-label="浏览器标签页"] [role="tab"]')?.id`);
  await clickButton('button[aria-label="新建浏览器标签"]');
  await typeAddress('http://127.0.0.1:5173/');
  await waitFor(`document.querySelectorAll('webview').length===2 && Math.abs((document.querySelectorAll('webview')[1]?.getZoomFactor?.()||1)-1)<0.01`, 'new tab default zoom');
  await evaluate(`document.getElementById(${JSON.stringify(firstTabId)})?.click()`);
  await waitFor(`Math.abs(${activeZoom}-1.1)<0.01`, 'restored zoom on first tab');

  // Reset to 100%, then use Ctrl+wheel to confirm wheel adjustment from the live page.
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: '0', code: 'Digit0', modifiers: 2, windowsVirtualKeyCode: 48 });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: '0', code: 'Digit0', modifiers: 2, windowsVirtualKeyCode: 48 });
  await waitFor(`Math.abs(${activeZoom}-1)<0.01`, 'Ctrl+0 reset');
  await evaluate(`(()=>{const v=[...document.querySelectorAll('webview')].find(x=>x.parentElement?.parentElement?.getAttribute('aria-hidden')==='false');return v.sendInputEvent({type:'mouseWheel',x:100,y:100,wheelTicksY:1,wheelTicksX:0,deltaY:0,deltaX:0,modifiers:['ctrl']})})()`);
  await waitFor(`Math.abs(${activeZoom}-1.2)<0.01`, 'Ctrl+wheel zoom');
  const wheelBanner = await evaluate(`document.querySelector('[aria-label="网页缩放"]')?.innerText`);
  if (!String(wheelBanner).includes('120%')) throw new Error(`Ctrl+wheel banner did not show the current 120% zoom: ${wheelBanner}`);

  const currentTabId = await evaluate(`document.querySelector('[role="tablist"][aria-label="浏览器标签页"] [role="tab"][aria-selected="true"]')?.id`);
  await evaluate(`([...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='重置网页缩放'))?.click()`);
  await waitFor(`Math.abs(${activeZoom}-1)<0.01`, 'reset button');
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: '+', code: 'Equal', modifiers: 2, windowsVirtualKeyCode: 187 });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: '+', code: 'Equal', modifiers: 2, windowsVirtualKeyCode: 187 });
  await waitFor(`Math.abs(${activeZoom}-1.1)<0.01`, 'zoom before closing tab');
  await evaluate(`document.getElementById(${JSON.stringify(currentTabId)})?.parentElement?.querySelector('button[aria-label^="关闭标签："]')?.click()`);
  await waitFor(`document.querySelectorAll('[role="tablist"][aria-label="浏览器标签页"] [role="tab"]').length===1`, 'close tab');
  const restored = await evaluate(activeZoom);
  if (Math.abs(restored - 1) > 0.01) throw new Error(`Closing the zoomed tab did not leave the remaining tab at its default: ${restored}`);
  console.log('U44 item 7 PASS: live webview keyboard, wheel, per-tab retention, reset, and close behavior');
} finally {
  socket.close();
}
