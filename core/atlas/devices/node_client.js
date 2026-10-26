/* Browser-backed paired node capability executor. Permission prompts remain
   native to the device browser; the page never uploads media unless an agent
   explicitly invokes camera.capture on an approved paired node. */
(() => {
  const status = document.getElementById('status');
  const commandList = document.getElementById('commandList');
  const api = async (path, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (options.auth) headers.Authorization = `Bearer ${localStorage.getItem('atlas-device-token') || ''}`;
    const response = await fetch(path, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  };
  const deviceId = () => localStorage.getItem('atlas-device-id') || '';
  const finish = async (item, value) => {
    await api(`/api/devices/node/${encodeURIComponent(deviceId())}/commands/${encodeURIComponent(item.id)}/result`, {
      method: 'POST', auth: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ result: JSON.stringify(value) }),
    });
  };
  const audio = new Audio();
  audio.preload = 'none';
  const run = async ({ item, task }) => {
    const args = task.arguments || {};
    try {
      let result;
      if (task.kind === 'status') {
        let battery = null;
        try { if (navigator.getBattery) { const value = await navigator.getBattery(); battery = { level: value.level, charging: value.charging }; } } catch { /* unavailable on this browser */ }
        result = { ok: true, online: navigator.onLine, platform: navigator.platform, language: navigator.language,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, user_agent: navigator.userAgent, battery,
          supported: { camera: Boolean(navigator.mediaDevices?.getUserMedia), location: Boolean(navigator.geolocation), notification: Boolean(window.Notification), media: true } };
      } else if (task.kind === 'notification') {
        if (!window.Notification) throw new Error('此设备浏览器不支持通知');
        let permission = Notification.permission;
        if (permission === 'default') permission = await Notification.requestPermission();
        if (permission !== 'granted') throw new Error(`通知权限${permission === 'denied' ? '已拒绝' : '未授予'}`);
        new Notification(String(args.title || 'Atlas'), { body: String(args.message || ''), tag: `atlas-${item.id}` });
        result = { ok: true, delivered: true, permission };
      } else if (task.kind === 'camera') {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('此设备浏览器不支持摄像头采集');
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: args.facing_mode || 'environment' }, audio: false });
        try {
          const video = document.createElement('video'); video.srcObject = stream; video.muted = true;
          await video.play(); await new Promise((resolve) => video.videoWidth ? resolve() : video.addEventListener('loadedmetadata', resolve, { once: true }));
          const canvas = document.createElement('canvas'); canvas.width = video.videoWidth; canvas.height = video.videoHeight;
          canvas.getContext('2d').drawImage(video, 0, 0); result = { ok: true, mime_type: 'image/jpeg', width: canvas.width, height: canvas.height, data_url: canvas.toDataURL('image/jpeg', 0.78) };
        } finally { stream.getTracks().forEach((track) => track.stop()); }
      } else if (task.kind === 'location') {
        if (!navigator.geolocation) throw new Error('此设备浏览器不支持定位');
        const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 }));
        result = { ok: true, latitude: position.coords.latitude, longitude: position.coords.longitude,
          accuracy_m: position.coords.accuracy, altitude_m: position.coords.altitude, heading: position.coords.heading,
          speed_mps: position.coords.speed, captured_at: new Date(position.timestamp).toISOString() };
      } else if (task.kind === 'media') {
        const action = args.action;
        if (action === 'play') {
          const url = new URL(String(args.url || ''), location.href);
          if (!['https:', 'http:'].includes(url.protocol)) throw new Error('媒体 URL 仅支持 HTTP(S)');
          audio.src = url.href; audio.volume = 1; await audio.play();
        } else if (action === 'pause') audio.pause();
        else if (action === 'resume') await audio.play();
        else if (action === 'stop') { audio.pause(); audio.removeAttribute('src'); audio.load(); }
        else if (action === 'volume') { audio.volume = Math.max(0, Math.min(1, Number(args.volume))); }
        else throw new Error('媒体操作必须是 play、pause、resume、stop 或 volume');
        result = { ok: true, action, paused: audio.paused, volume: audio.volume, current_time_s: audio.currentTime };
      } else throw new Error(`不支持节点能力：${task.kind}`);
      await finish(item, result);
      if (status) status.textContent = `节点能力 ${task.kind} 已完成并返回 Atlas。`;
    } catch (error) {
      try { await finish(item, { ok: false, error: String(error?.message || error) }); }
      catch (sendError) { if (status) status.textContent = `节点执行失败且无法回传：${String(sendError)}`; return; }
      if (status) status.textContent = `节点执行失败：${String(error?.message || error)}`;
    }
  };
  window.addEventListener('atlas-node-command', (event) => {
    const { item, task } = event.detail;
    const needsLocalAction = ['camera', 'location', 'notification'].includes(task.kind)
      || (task.kind === 'media' && task.arguments?.action === 'play');
    if (!needsLocalAction) { void run(event.detail); return; }
    const article = document.createElement('article'); article.className = 'row';
    const text = document.createElement('p'); text.textContent = `Atlas 请求在此设备执行 ${task.kind}。继续会触发浏览器权限提示（若尚未授予），或开始媒体播放。`;
    const button = document.createElement('button'); button.type = 'button'; button.textContent = `在本机运行 ${task.kind}`;
    button.onclick = () => { button.disabled = true; void run(event.detail).finally(() => article.remove()); };
    article.append(text, button); commandList?.prepend(article);
  });
  const unlock = document.getElementById('mediaUnlock');
  if (unlock) unlock.addEventListener('click', async () => {
    try { audio.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA='; await audio.play(); audio.pause(); audio.removeAttribute('src'); audio.load(); unlock.textContent = '媒体播放已就绪'; }
    catch (error) { if (status) status.textContent = `媒体播放初始化失败：${String(error)}`; }
  });
  const capabilityNames = [
    'device.status',
    ...(window.Notification ? ['notifications.send'] : []),
    ...(navigator.mediaDevices?.getUserMedia ? ['camera.capture'] : []),
    ...(navigator.geolocation ? ['location.read'] : []),
    'media.control',
  ];
  if (commandList && !document.getElementById('mediaUnlock')) {
    const button = document.createElement('button'); button.id = 'mediaUnlock'; button.type = 'button'; button.className = 'secondary';
    button.textContent = '启用本机媒体播放'; commandList.before(button);
  }
  window.atlasNodeCapabilities = capabilityNames;
})();
