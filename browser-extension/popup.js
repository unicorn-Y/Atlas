const $ = (id) => document.getElementById(id);
async function refresh() {
  const tabs = await chrome.tabs.query({});
  $('tabs').replaceChildren(...tabs.filter((tab) => tab.id != null).map((tab) => {
    const option = document.createElement('option'); option.value = String(tab.id); option.textContent = `${tab.title || tab.url}`; return option;
  }));
  const state = await chrome.runtime.sendMessage({ type: 'state' });
  $('state').textContent = state.connected ? (state.tabId ? `已连接并控制标签页 ${state.tabId}` : '已配对，尚未选择受控标签页') : '未连接到 Atlas。请启动 Atlas 后重试。';
}
$('pair').onclick = async () => { await chrome.runtime.sendMessage({ type: 'pair', code: $('code').value.trim() }); $('state').textContent = '正在验证配对码…'; };
$('attach').onclick = async () => { const result = await chrome.runtime.sendMessage({ type: 'attach', tabId: $('tabs').value }); $('state').textContent = result.ok ? `Atlas 正在控制：${result.title || result.url}` : result.error; };
$('detach').onclick = async () => { await chrome.runtime.sendMessage({ type: 'detach' }); await refresh(); };
chrome.runtime.onMessage.addListener((msg) => { if (msg.type === 'paired') $('state').textContent = '配对成功。选择标签页并接管。'; if (msg.type === 'pair-error') $('state').textContent = msg.error; });
refresh();
