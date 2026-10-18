import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, nativeImage, session, shell, Tray } from 'electron';
import { randomBytes, randomUUID } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { appendFileSync, chmodSync, existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { setImmediate } from 'node:timers';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ensureBackendRunning, readRunningBackendPid, stopManagedBackend, terminateBackendPid } from './backendProcess.js';
import { checkSourceUpdate, launchSourceUpdater, sourceRoot } from './sourceUpdate.js';
import {
  BACKEND_STARTUP_CHANNEL,
  type AtlasDeepLink,
  type AtlasSettingsSection,
  type BackendStartupProgress,
  type GlobalShortcutState,
  type PlatformEditorId,
  type PlatformSettingsState,
} from '../shared/ipc.js';

const here = path.dirname(fileURLToPath(import.meta.url));
if (process.env.ATLAS_DESKTOP_USER_DATA_DIR) {
  app.setPath('userData', path.resolve(process.env.ATLAS_DESKTOP_USER_DATA_DIR));
}

/** Window/taskbar icon per UI theme (assets/icon/icon-<theme>.png); the exe icon stays 夜航. */
const THEME_ICONS = new Set(['light', 'aurora', 'dark']);
function themeIcon(theme: string): Electron.NativeImage | undefined {
  if (!THEME_ICONS.has(theme)) return undefined;
  const image = nativeImage.createFromPath(path.join(app.getAppPath(), 'assets', 'icon', `icon-${theme}.png`));
  return image.isEmpty() ? undefined : image;
}
let windowRef: BrowserWindow | null = null;
let floatingComposerWindow: BrowserWindow | null = null;
type PlatformPreferences = { alwaysOnTop: boolean; globalShortcut: string | null; openAtLogin: boolean };
let platformPreferences: PlatformPreferences = { alwaysOnTop: false, globalShortcut: null, openAtLogin: true };
let globalShortcutState: GlobalShortcutState = { accelerator: null, registered: false };
let pendingDeepLinks: AtlasDeepLink[] = [];
let deepLinkSubscriber: Electron.WebContents | null = null;
process.env.ATLAS_SKILL_CENTER_TOKEN ??= randomBytes(32).toString('base64url');
let trayRef: Tray | null = null;
let backendAttempt = 0;
let pendingRetry: NodeJS.Timeout | null = null;
let trayRefreshTimer: NodeJS.Timeout | null = null;
let explicitQuit = false;
let lastProgress: BackendStartupProgress = { phase: 'probing', managed: false, elapsedMs: 0 };
let componentStatuses: Record<string, string> = {};
let consecutiveBackendHealthFailures = 0;
let backendAvailability: BackendAvailability = 'unknown';

/** Session for pages shown in the browser panel. Separate from the app's, so they never get the backend token. */
export const BROWSER_PARTITION = 'persist:atlas-browser';

const SETTINGS_SECTIONS = new Set<AtlasSettingsSection>([
  'models', 'advanced', 'usage', 'limits', 'profiles', 'hooks', 'tools', 'telegram', 'channels',
  'devices', 'localModels', 'shortcuts', 'appearance', 'plugins', 'notifications', 'mcp',
  'skills', 'recipes', 'extensions', 'transfer', 'diagnostics', 'security', 'commands', 'platform', 'integrations', 'network',
]);
const ACCELERATOR_KEYS = new Set([
  'Space', 'Escape', 'Tab', 'Return', 'Backspace', 'Delete', 'Insert', 'Home', 'End',
  'PageUp', 'PageDown', 'Up', 'Down', 'Left', 'Right', 'Plus', 'Minus', 'Comma', 'Period',
]);
const RESERVED_ACCELERATORS = new Set([
  'Alt+F4', 'Control+F4', 'CommandOrControl+Q', 'Control+Q', 'CommandOrControl+W', 'Control+W',
  'Super+L', 'Super+Tab', 'CommandOrControl+Alt+Delete',
].map((accelerator) => accelerator.toLowerCase()));
const IDE_COMMANDS: Record<PlatformEditorId, string> = {
  vscode: process.platform === 'win32' ? 'Code.exe' : 'code',
  cursor: process.platform === 'win32' ? 'Cursor.exe' : 'cursor',
  zed: process.platform === 'win32' ? 'zed.exe' : 'zed',
  idea: process.platform === 'win32' ? 'idea64.exe' : 'idea',
  pycharm: process.platform === 'win32' ? 'pycharm64.exe' : 'pycharm',
  webstorm: process.platform === 'win32' ? 'webstorm64.exe' : 'webstorm',
  goland: process.platform === 'win32' ? 'goland64.exe' : 'goland',
  rider: process.platform === 'win32' ? 'rider64.exe' : 'rider',
  clion: process.platform === 'win32' ? 'clion64.exe' : 'clion',
  phpstorm: process.platform === 'win32' ? 'phpstorm64.exe' : 'phpstorm',
  rubymine: process.platform === 'win32' ? 'rubymine64.exe' : 'rubymine',
  datagrip: process.platform === 'win32' ? 'datagrip64.exe' : 'datagrip',
};

function preferencesPath(): string {
  return path.join(app.getPath('userData'), 'platform-settings.json');
}

function loadPlatformPreferences(): PlatformPreferences {
  try {
    const data = JSON.parse(readFileSync(preferencesPath(), 'utf8')) as Record<string, unknown>;
    return {
      alwaysOnTop: data.alwaysOnTop === true,
      globalShortcut: typeof data.globalShortcut === 'string' ? data.globalShortcut : null,
      openAtLogin: data.openAtLogin !== false,
    };
  } catch {
    return { alwaysOnTop: false, globalShortcut: null, openAtLogin: true };
  }
}

function savePlatformPreferences(next: PlatformPreferences): void {
  const target = preferencesPath();
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
  platformPreferences = next;
}

function platformSettingsSnapshot(): PlatformSettingsState {
  return { alwaysOnTop: platformPreferences.alwaysOnTop, openAtLogin: platformPreferences.openAtLogin, globalShortcut: { ...globalShortcutState } };
}

function runtimeDir(): string {
  const dataDir = process.env.ATLAS_DATA_DIR
    ? path.join(path.resolve(process.env.ATLAS_DATA_DIR), 'data')
    : app.isPackaged ? app.getPath('userData') : path.resolve(app.getAppPath(), '..', 'data');
  return path.join(dataDir, 'runtime');
}

function prepareSharedApiToken(): void {
  const dir = runtimeDir();
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'api-token');
  let token = '';
  try { token = readFileSync(file, 'utf8').trim(); } catch { /* create below */ }
  if (!token) {
    token = randomBytes(32).toString('base64url');
    writeFileSync(file, `${token}\n`, { mode: 0o600 });
  }
  try { chmodSync(file, 0o600); } catch { /* Windows ACL is handled below */ }
  if (process.platform === 'win32') restrictTokenFile(file);
  process.env.ATLAS_API_TOKEN = token;
}

/** Best effort: let only the current account read the shared token. DOMAIN\USERNAME from the
 * environment does not always resolve (icacls exit 1332 on the 主机 stopped startup before the
 * window existed), so grant by SID. A failure is logged, never fatal: the file already lives in
 * the user's own data directory. */
function restrictTokenFile(file: string): void {
  let account = process.env.USERNAME ?? '';
  const who = spawnSync('whoami', ['/user', '/fo', 'csv', '/nh'], { windowsHide: true, encoding: 'utf8' });
  const sid = who.status === 0 ? /"(S-1-[0-9-]+)"/.exec(who.stdout ?? '')?.[1] : undefined;
  if (sid) account = `*${sid}`;
  else if (process.env.USERDOMAIN && account) account = `${process.env.USERDOMAIN}\\${account}`;
  const acl = spawnSync('icacls', [file, '/inheritance:r', '/grant:r', `${account}:(R)`], { windowsHide: true, stdio: 'ignore' });
  if (acl.error || acl.status !== 0) {
    console.warn(`Atlas: could not restrict the shared API token file (icacls ${acl.error?.message ?? `exit ${acl.status}`}); continuing`);
  }
}

function setOpenAtLogin(enabled: boolean): void {
  platformPreferences = { ...platformPreferences, openAtLogin: enabled };
  savePlatformPreferences(platformPreferences);
  app.setLoginItemSettings({ openAtLogin: enabled, args: enabled ? ['--background'] : [] });
}

function buildTrayMenu(): void {
  if (!trayRef) return;
  const busyNote = backendAvailability === 'degraded' ? '（响应慢，仍在运行）' : '';
  const statusText = lastProgress.phase === 'ready' ? `后台：可用${busyNote}`
    : lastProgress.phase === 'failed' ? `后台：启动失败${lastProgress.detail ? `（${lastProgress.detail.slice(0, 60)}）` : ''}`
      : `后台：${lastProgress.detail || '正在启动'}`;
  trayRef.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 Atlas', click: focusAtlasWindow },
    { label: statusText, enabled: false },
    { label: '后台组件', submenu: Object.entries(componentStatuses).length
      ? Object.entries(componentStatuses).map(([name, state]) => ({ label: `${name}：${state}`, enabled: false }))
      : [{ label: '等待状态', enabled: false }] },
    { label: '重启后台', click: () => { void restartBackendNow('tray_menu'); } },
    { label: '查看日志', click: () => { void shell.openPath(backendLogPath()); } },
    { type: 'separator' },
    { label: '开机自启', type: 'checkbox', checked: platformPreferences.openAtLogin, click: (item) => setOpenAtLogin(item.checked) },
    { type: 'separator' },
    { label: '退出 Atlas', click: () => { explicitQuit = true; app.quit(); } },
  ]));
}

function createTray(): void {
  if (trayRef) return;
  const image = nativeImage.createFromPath(path.join(app.getAppPath(), 'assets', 'icon', 'icon-dark.png'));
  trayRef = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image);
  trayRef.setToolTip('Atlas');
  trayRef.on('double-click', focusAtlasWindow);
  buildTrayMenu();
}

function backendLogPath(): string {
  if (process.env.ATLAS_DATA_DIR) return path.join(path.resolve(process.env.ATLAS_DATA_DIR), 'data', 'logs', 'backend-stdio.log');
  if (app.isPackaged) return path.join(app.getPath('userData'), 'data', 'logs', 'backend-stdio.log');
  return path.resolve(app.getAppPath(), '..', 'data', 'logs', 'backend-stdio.log');
}

type BackendAvailability = 'unknown' | 'ok' | 'degraded';

/** Diagnostic trail for probe/restart decisions: "why was it killed" must be answerable. */
function recordDesktopLifecycle(event: string, fields: Record<string, unknown>): void {
  try {
    appendFileSync(backendLogPath(), `${JSON.stringify({ timestamp: new Date().toISOString(), event, ...fields })}\n`);
  } catch {
    // A diagnostic sink must never break the tray.
  }
}

async function refreshTrayBackendStatus(): Promise<void> {
  try {
    const response = await fetch(`http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}/api/health`, { signal: AbortSignal.timeout(1_500) });
    if (!response.ok) { componentStatuses = {}; recordBackendHealthFailure(); buildTrayMenu(); return; }
    consecutiveBackendHealthFailures = 0;
    backendAvailability = 'ok';
    buildTrayMenu();
    const body = await response.json() as { components?: Record<string, string | { status?: string }> };
    componentStatuses = Object.fromEntries(Object.entries(body.components ?? {}).map(([name, item]) => [
      name, typeof item === 'string' ? item : item?.status ?? 'unknown',
    ]));
    buildTrayMenu();
  } catch { componentStatuses = {}; recordBackendHealthFailure(); buildTrayMenu(); }
}

/**
 * A missed probe means "busy or degraded", never "dead". Killing a slow backend aborted
 * whatever the user was running, so a restart is left to the user or to real process
 * exit; the tray only reports the degraded state.
 */
function recordBackendHealthFailure(): void {
  consecutiveBackendHealthFailures += 1;
  // A slow answer is not evidence of death, but a vanished pid is. Verifying the pid is
  // expensive (netstat + PowerShell), so only ask once a probe has failed twice - and
  // this is the only signal allowed to trigger an automatic restart.
  if (consecutiveBackendHealthFailures >= 2 && lastProgress.phase === 'ready') {
    const pid = readRunningBackendPid();
    if (pid === null) {
      if (backendAvailability !== 'degraded') {
        backendAvailability = 'degraded';
        recordDesktopLifecycle('backend.health_degraded', {
          consecutive_failures: consecutiveBackendHealthFailures,
          action: 'restart',
          note: 'process is gone, not slow; restarting',
        });
      }
      startBackend();
      return;
    }
    // Alive and ours: report it, never end it.
    if (backendAvailability !== 'degraded') {
      backendAvailability = 'degraded';
      recordDesktopLifecycle('backend.health_degraded', {
        consecutive_failures: consecutiveBackendHealthFailures,
        action: 'none',
        note: 'left running deliberately: a slow backend is not a dead backend',
        pid,
      });
    }
  }
}

function publishProgress(progress: BackendStartupProgress): void {
  lastProgress = progress;
  windowRef?.webContents.send(BACKEND_STARTUP_CHANNEL, progress);
  buildTrayMenu();
}

function startBackend(manual = false): void {
  if (pendingRetry) { clearTimeout(pendingRetry); pendingRetry = null; }
  const attempt = ++backendAttempt;
  if (manual) retryCount = 0;
  void ensureBackendRunning({ onProgress: publishProgress }).then(() => {
    if (attempt !== backendAttempt) return;
    retryCount = 0;
  }).catch((error: unknown) => {
    if (attempt !== backendAttempt || explicitQuit) return;
    const message = error instanceof Error ? error.message : String(error);
    const detail = message.slice(-6000);
    publishProgress({ phase: 'failed', managed: false, elapsedMs: lastProgress.elapsedMs, detail, message: detail, logPath: backendLogPath() });
    if (retryCount < 3) {
      const delay = [1_000, 3_000, 10_000][retryCount++];
      pendingRetry = setTimeout(() => { pendingRetry = null; startBackend(); }, delay);
    }
  });
}
let retryCount = 0;

function validateGlobalAccelerator(value: string): string | null {
  const accelerator = value.trim();
  if (!accelerator || accelerator.length > 80) return '请填写长度不超过 80 个字符的快捷键。';
  const parts = accelerator.split('+').map((part) => part.trim());
  const key = parts.pop() ?? '';
  const allowedModifiers = new Set(['CommandOrControl', 'Control', 'Alt', 'Shift', 'Super']);
  if (!key || parts.length === 0 || parts.length > 3 || parts.some((part) => !allowedModifiers.has(part))) {
    return '格式示例：CommandOrControl+Shift+Space。';
  }
  if (new Set(parts).size !== parts.length || !parts.some((part) => part !== 'Shift')) {
    return '快捷键必须有 Ctrl、Alt、CommandOrControl 或 Super 修饰键。';
  }
  const validKey = /^[A-Z0-9]$/i.test(key) || /^F(?:[1-9]|1[0-9]|2[0-4])$/i.test(key)
    || [...ACCELERATOR_KEYS].some((candidate) => candidate.toLowerCase() === key.toLowerCase());
  if (!validKey) return '不支持这个按键名称。';
  const canonical = [...parts, key].join('+');
  if (RESERVED_ACCELERATORS.has(canonical.toLowerCase())) return '这个快捷键保留给系统或应用。';
  return null;
}

function focusAtlasWindow(): void {
  if (!app.isReady()) return;
  if (!windowRef || windowRef.isDestroyed()) createWindow();
  if (!windowRef || windowRef.isDestroyed()) return;
  if (windowRef.isMinimized()) windowRef.restore();
  windowRef.show();
  windowRef.focus();
}

function showFloatingComposer(): void {
  if (!app.isReady()) return;
  if (!floatingComposerWindow || floatingComposerWindow.isDestroyed()) {
    const devUrl = process.env.VITE_DEV_SERVER_URL;
    const win = new BrowserWindow({
      width: 620,
      height: 190,
      minWidth: 420,
      minHeight: 170,
      maxWidth: 900,
      maxHeight: 320,
      show: false,
      frame: false,
      resizable: true,
      skipTaskbar: true,
      alwaysOnTop: true,
      backgroundColor: '#faf9f6',
      webPreferences: {
        preload: path.join(here, '../preload/index.cjs'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    floatingComposerWindow = win;
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event, url) => {
      const allowed = devUrl ? (() => { try {
        const target = new URL(url);
        return target.origin === new URL(devUrl).origin && target.pathname.endsWith('/floating-composer.html');
      } catch { return false; } })()
        : url.split('#')[0] === pathToFileURL(path.resolve(here, '../../dist/floating-composer.html')).href;
      if (!allowed) event.preventDefault();
    });
    win.on('closed', () => { if (floatingComposerWindow === win) floatingComposerWindow = null; });
    if (devUrl) void win.loadURL(`${devUrl.replace(/\/$/, '')}/floating-composer.html`);
    else void win.loadFile(path.join(here, '../../dist/floating-composer.html'));
    win.once('ready-to-show', () => { win.show(); win.focus(); });
  } else {
    floatingComposerWindow.show();
    floatingComposerWindow.focus();
  }
}

function tryRegisterGlobalShortcut(accelerator: string | null): GlobalShortcutState {
  if (!accelerator) return { accelerator: null, registered: false };
  const invalid = validateGlobalAccelerator(accelerator);
  if (invalid) return { accelerator, registered: false, error: invalid };
  try {
    const registered = globalShortcut.register(accelerator, focusAtlasWindow);
    return registered
      ? { accelerator, registered: true }
      : { accelerator, registered: false, error: '系统未能注册此快捷键，可能已被其他应用占用。' };
  } catch {
    return { accelerator, registered: false, error: '系统未能注册此快捷键。' };
  }
}

function registerPreferredGlobalShortcut(): void {
  globalShortcutState = tryRegisterGlobalShortcut(platformPreferences.globalShortcut);
}

function assertTrustedAppSender(event: Electron.IpcMainEvent | Electron.IpcMainInvokeEvent): void {
  if (event.sender !== windowRef?.webContents || event.senderFrame !== event.sender.mainFrame) {
    throw new Error('此操作仅允许 Atlas 主窗口调用。');
  }
  const url = event.senderFrame.url;
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  const appFileUrl = pathToFileURL(path.resolve(here, '../../dist/index.html')).href;
  let trusted = url.split('#')[0] === appFileUrl;
  if (devUrl) {
    try { trusted = new URL(url).origin === new URL(devUrl).origin; } catch { trusted = false; }
  }
  if (!trusted) throw new Error('此操作仅允许 Atlas 应用页面调用。');
}

function parseAtlasDeepLink(raw: string): AtlasDeepLink | null {
  try {
    const url = new URL(raw);
    if (url.protocol !== 'atlas:' || url.username || url.password || url.port || url.search || url.hash) return null;
    const segments = url.pathname.split('/').filter(Boolean).map((segment) => decodeURIComponent(segment));
    if (segments.length !== 1) return null;
    if (url.hostname === 'conversation' && /^[A-Za-z0-9_-]{1,128}$/.test(segments[0])) {
      return { id: randomUUID(), type: 'conversation', conversationId: segments[0] };
    }
    if (url.hostname === 'settings' && SETTINGS_SECTIONS.has(segments[0] as AtlasSettingsSection)) {
      return { id: randomUUID(), type: 'settings', section: segments[0] as AtlasSettingsSection };
    }
  } catch {
    return null;
  }
  return null;
}

function receiveAtlasDeepLink(raw: string): boolean {
  const route = parseAtlasDeepLink(raw);
  if (!route) return false;
  if (deepLinkSubscriber && !deepLinkSubscriber.isDestroyed()) {
    deepLinkSubscriber.send('app:deep-link', route);
  } else {
    pendingDeepLinks.push(route);
    if (pendingDeepLinks.length > 32) pendingDeepLinks = pendingDeepLinks.slice(-32);
  }
  focusAtlasWindow();
  return true;
}

function findAtlasUrl(args: string[]): string | null {
  return args.find((arg) => /^atlas:/i.test(arg)) ?? null;
}

function setGlobalShortcut(accelerator: string | null): GlobalShortcutState {
  if (accelerator !== null) {
    const invalid = validateGlobalAccelerator(accelerator);
    if (invalid) return { accelerator, registered: false, error: invalid };
  }

  const previousAccelerator = platformPreferences.globalShortcut;
  const wasRegistered = globalShortcutState.registered;
  const next = { ...platformPreferences, globalShortcut: accelerator };
  savePlatformPreferences(next);
  if (previousAccelerator && wasRegistered) {
    globalShortcut.unregister(previousAccelerator);
  }
  globalShortcutState = tryRegisterGlobalShortcut(accelerator);
  return { ...globalShortcutState };
}

function openWorkspaceInEditor(editor: PlatformEditorId, workspacePath: string): Promise<void> {
  if (!Object.hasOwn(IDE_COMMANDS, editor)) throw new Error('不支持的编辑器。');
  if (typeof workspacePath !== 'string' || !path.isAbsolute(workspacePath)) {
    throw new Error('请选择一个有效的本地工作区目录。');
  }
  let canonicalPath: string;
  try {
    canonicalPath = realpathSync(workspacePath);
    if (!statSync(canonicalPath).isDirectory()) throw new Error('工作区路径不是目录。');
  } catch (error) {
    if (error instanceof Error && error.message === '工作区路径不是目录。') throw error;
    throw new Error('工作区目录不存在或无法访问。');
  }
  return new Promise((resolve, reject) => {
    const child = spawn(IDE_COMMANDS[editor], [canonicalPath], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      shell: false,
    });
    child.once('error', (error) => {
      if ('code' in error && error.code === 'ENOENT') {
        reject(new Error(`未找到 ${editor} 命令行工具。请安装该编辑器并将其命令加入 PATH。`));
      } else {
        reject(new Error(`无法启动 ${editor}：${error.message}`));
      }
    });
    child.once('spawn', () => {
      child.unref();
      resolve();
    });
  });
}

function openFileInEditor(editor: PlatformEditorId, workspacePath: string, filePath: string): Promise<void> {
  if (!Object.hasOwn(IDE_COMMANDS, editor)) throw new Error('不支持的编辑器。');
  if (typeof workspacePath !== 'string' || !path.isAbsolute(workspacePath) || typeof filePath !== 'string' || !path.isAbsolute(filePath)) {
    throw new Error('请选择一个有效的本地工作区文件。');
  }
  let canonicalRoot: string;
  let canonicalFile: string;
  try {
    canonicalRoot = realpathSync(workspacePath);
    canonicalFile = realpathSync(filePath);
    if (!statSync(canonicalFile).isFile()) throw new Error('目标路径不是文件。');
    const relative = path.relative(canonicalRoot, canonicalFile);
    if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
      throw new Error('目标文件必须位于当前工作区中。');
    }
  } catch (error) {
    if (error instanceof Error && ['目标路径不是文件。', '目标文件必须位于当前工作区中。'].includes(error.message)) throw error;
    throw new Error('工作区文件不存在或无法访问。');
  }
  return new Promise((resolve, reject) => {
    const child = spawn(IDE_COMMANDS[editor], [canonicalFile], { detached: true, stdio: 'ignore', windowsHide: true, shell: false });
    child.once('error', (error) => reject('code' in error && error.code === 'ENOENT'
      ? new Error(`未找到 ${editor} 命令行工具。请安装该编辑器并将其命令加入 PATH.`)
      : new Error(`无法启动 ${editor}：${error.message}`)));
    child.once('spawn', () => { child.unref(); resolve(); });
  });
}

/** Pages in the browser panel are ordinary web content: no preload, no Node, their own session, web URLs only. */
function lockDownWebviews() {
  app.on('web-contents-created', (_event, contents) => {
    contents.on('will-attach-webview', (event, preferences, params) => {
      delete preferences.preload;
      preferences.nodeIntegration = false;
      preferences.nodeIntegrationInSubFrames = false;
      preferences.contextIsolation = true;
      preferences.sandbox = true;
      params.partition = BROWSER_PARTITION;
      if (params.src && !/^(https?:|file:|about:blank)/i.test(params.src)) event.preventDefault();
    });
    if (contents.getType() === 'webview') {
      // Links that would open a new window stay in the panel instead.
      contents.setWindowOpenHandler(({ url }) => {
        if (/^https?:/i.test(url)) void contents.loadURL(url);
        return { action: 'deny' };
      });
    }
  });
}

function attachBackendToken() {
  const port = process.env.ATLAS_PORT ?? '8765';
  const urls = ['127.0.0.1', 'localhost'].flatMap((host) => [`http://${host}:${port}/*`, `ws://${host}:${port}/*`]);
  session.defaultSession.webRequest.onBeforeSendHeaders({ urls }, (details, callback) => {
    // Only Atlas's own page gets the token. Frames inside it (file previews) show workspace content,
    // which is untrusted: anything they load or fetch goes out without it.
    const fromSubframe = details.resourceType === 'subFrame' || Boolean(details.frame?.parent);
    if (fromSubframe) { callback({ requestHeaders: details.requestHeaders }); return; }
    callback({ requestHeaders: { ...details.requestHeaders, 'X-Atlas-Api-Token': process.env.ATLAS_API_TOKEN ?? '' } });
  });
}

function createWindow() {
  if (windowRef && !windowRef.isDestroyed()) {
    windowRef.show();
    windowRef.focus();
    return;
  }
  windowRef = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1050,
    minHeight: 680,
    backgroundColor: '#faf9f6',
    title: 'Atlas · Agent Workspace',
    icon: themeIcon('dark'),
    titleBarStyle: 'hidden',
    show: false,
    trafficLightPosition: { x: 14, y: 13 },
    webPreferences: {
      preload: path.join(here, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // The browser panel renders pages in <webview>; see lockDownWebviews for what they may do.
      webviewTag: true,
    },
  });
  windowRef.once('ready-to-show', () => { if (!explicitQuit && !process.argv.includes('--background')) windowRef?.show(); });
  windowRef.setAlwaysOnTop(platformPreferences.alwaysOnTop);

  windowRef.on('maximize', () => windowRef?.webContents.send('window:maximize-change', true));
  windowRef.on('unmaximize', () => windowRef?.webContents.send('window:maximize-change', false));
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  // The app window carries the preload API and its requests get the backend token, so it must
  // never become a window onto someone else's page: links open in the system browser instead,
  // and navigation away from the app is refused.
  const appUrl = devUrl ? new URL(devUrl).origin : pathToFileURL(path.join(here, '../../dist/index.html')).href;
  const isAppUrl = (target: string) => {
    if (!devUrl) return target.split('#')[0] === appUrl;
    try {
      return new URL(target).origin === appUrl;
    } catch {
      return false;
    }
  };
  windowRef.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  windowRef.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return;
    event.preventDefault();
    if (/^atlas:/i.test(url)) receiveAtlasDeepLink(url);
    else if (/^https?:/i.test(url)) void shell.openExternal(url);
  });
  const win = windowRef;
  const loadApp = () => {
    if (devUrl) void win.loadURL(devUrl);
    else void win.loadFile(path.join(here, '../../dist/index.html'));
  };
  loadApp();
  // A dead renderer or a failed first paint would otherwise leave an all-white
  // window until the user manually restarts: bring the page back on its own.
  win.webContents.on('render-process-gone', (_event, details) => {
    if (details.reason === 'clean-exit') return;
    win.webContents.reload();
  });
  let loadRetries = 0;
  win.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame || code === -3) return; // -3: aborted by a newer navigation
    if (loadRetries >= 5) return;
    loadRetries += 1;
    setTimeout(() => loadApp(), 500 * loadRetries);
  });
  win.webContents.on('did-finish-load', () => { loadRetries = 0; });
  // Electron ships no right-click menu; give inputs and selected text the usual
  // edit menu. Pages that open their own menu call preventDefault and skip this.
  win.webContents.on('context-menu', (_event, params) => {
    const { editFlags, isEditable, selectionText } = params;
    const hasSelection = selectionText.trim().length > 0;
    if (!isEditable && !hasSelection) return;
    const items: Electron.MenuItemConstructorOptions[] = isEditable
      ? [
        { label: '撤销', role: 'undo', enabled: editFlags.canUndo },
        { label: '重做', role: 'redo', enabled: editFlags.canRedo },
        { type: 'separator' },
        { label: '剪切', role: 'cut', enabled: editFlags.canCut },
        { label: '复制', role: 'copy', enabled: editFlags.canCopy },
        { label: '粘贴', role: 'paste', enabled: editFlags.canPaste },
        { type: 'separator' },
        { label: '全选', role: 'selectAll', enabled: editFlags.canSelectAll },
      ]
      : [{ label: '复制', role: 'copy' }, { label: '全选', role: 'selectAll' }];
    Menu.buildFromTemplate(items).popup({ window: win });
  });
  win.webContents.on('did-start-loading', () => {
    if (deepLinkSubscriber === win.webContents) deepLinkSubscriber = null;
  });
  win.webContents.on('did-finish-load', () => {
    win.webContents.send(BACKEND_STARTUP_CHANNEL, lastProgress);
  });
  windowRef.on('close', (event) => {
    if (!explicitQuit) { event.preventDefault(); windowRef?.hide(); }
  });
  windowRef.on('closed', () => { windowRef = null; });
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', (_event, argv) => {
    const url = findAtlasUrl(argv);
    if (url) receiveAtlasDeepLink(url);
    else focusAtlasWindow();
  });
  app.on('open-url', (event, url) => {
    event.preventDefault();
    receiveAtlasDeepLink(url);
  });
}

ipcMain.handle('deep-link:subscribe', (event) => {
  assertTrustedAppSender(event);
  deepLinkSubscriber = event.sender;
  const queued = pendingDeepLinks;
  pendingDeepLinks = [];
  return queued;
});
ipcMain.on('deep-link:unsubscribe', (event) => {
  if (deepLinkSubscriber === event.sender) deepLinkSubscriber = null;
});
ipcMain.handle('platform:get-settings', (event) => {
  assertTrustedAppSender(event);
  return platformSettingsSnapshot();
});
ipcMain.handle('platform:set-always-on-top', (event, enabled: unknown) => {
  assertTrustedAppSender(event);
  if (typeof enabled !== 'boolean') throw new Error('置顶设置必须是布尔值。');
  savePlatformPreferences({ ...platformPreferences, alwaysOnTop: enabled });
  if (windowRef && !windowRef.isDestroyed()) windowRef.setAlwaysOnTop(enabled);
  return platformSettingsSnapshot();
});
ipcMain.handle('platform:set-open-at-login', (event, enabled: unknown) => {
  assertTrustedAppSender(event);
  if (typeof enabled !== 'boolean') throw new Error('开机自启设置必须是布尔值。');
  setOpenAtLogin(enabled);
  return platformSettingsSnapshot();
});
/**
 * The only path that ends a running backend. It is user-initiated (tray menu, explicit
 * restart IPC), never a probe result: a slow answer is not a reason to abort the user's
 * work. A backend we did not spawn is only replaced when the user asked for it here.
 */
async function restartBackendNow(reason: string): Promise<void> {
  await stopManagedBackend(reason);
  const pid = readRunningBackendPid();
  if (pid !== null) await terminateBackendPid(pid, reason);
  startBackend(true);
}

ipcMain.handle('backend:retry', (event) => {
  assertTrustedAppSender(event);
  void restartBackendNow('user_retry');
});
ipcMain.handle('backend:open-log', async (event) => {
  assertTrustedAppSender(event);
  const error = await shell.openPath(backendLogPath());
  if (error) throw new Error(error);
});
ipcMain.handle('platform:set-global-shortcut', (event, accelerator: unknown) => {
  assertTrustedAppSender(event);
  if (accelerator !== null && typeof accelerator !== 'string') throw new Error('快捷键格式无效。');
  return setGlobalShortcut(accelerator as string | null);
});
ipcMain.handle('platform:open-workspace-in-editor', async (event, editor: unknown, workspacePath: unknown) => {
  assertTrustedAppSender(event);
  if (typeof editor !== 'string' || !Object.prototype.hasOwnProperty.call(IDE_COMMANDS, editor)) {
    throw new Error('不支持的编辑器。');
  }
  if (typeof workspacePath !== 'string') throw new Error('请选择一个有效的本地工作区目录。');
  await openWorkspaceInEditor(editor as PlatformEditorId, workspacePath);
});
ipcMain.handle('floating-composer:show', (event) => {
  assertTrustedAppSender(event);
  showFloatingComposer();
});
ipcMain.on('floating-composer:hide', (event) => {
  if (event.sender === floatingComposerWindow?.webContents && event.senderFrame === event.sender.mainFrame) {
    floatingComposerWindow.hide();
  }
});
ipcMain.on('floating-composer:submit', (event, text: unknown) => {
  if (event.sender !== floatingComposerWindow?.webContents || event.senderFrame !== event.sender.mainFrame) return;
  if (typeof text !== 'string' || !text.trim() || text.length > 20_000) return;
  if (windowRef && !windowRef.isDestroyed()) {
    windowRef.webContents.send('floating-composer:deliver', text.trim());
    focusAtlasWindow();
  }
  floatingComposerWindow?.hide();
});

ipcMain.handle('platform:open-file-in-editor', async (event, editor: unknown, workspacePath: unknown, filePath: unknown) => {
  assertTrustedAppSender(event);
  if (typeof editor !== 'string' || !Object.prototype.hasOwnProperty.call(IDE_COMMANDS, editor)) throw new Error('不支持的编辑器。');
  if (typeof workspacePath !== 'string' || typeof filePath !== 'string') throw new Error('请选择一个有效的本地工作区文件。');
  await openFileInEditor(editor as PlatformEditorId, workspacePath, filePath);
});

ipcMain.on('window:minimize', () => windowRef?.minimize());
ipcMain.on('window:maximize', () => {
  if (!windowRef) return;
  if (windowRef.isMaximized()) windowRef.unmaximize();
  else windowRef.maximize();
});
ipcMain.on('window:close', () => windowRef?.close());
// Source mode (running from a git checkout without the Vite dev server): updates are
// pulled and rebuilt by scripts/atlas-update.mjs instead of reinstalling a package.
const updateRoot = () => (!app.isPackaged && !process.env.VITE_DEV_SERVER_URL ? sourceRoot(app.getAppPath()) : null);
ipcMain.handle('update:check', () => checkSourceUpdate(updateRoot()));
ipcMain.handle('update:apply', async () => {
  const root = updateRoot();
  if (!root) return false;
  await stopManagedBackend();
  launchSourceUpdater(root);
  setImmediate(() => { explicitQuit = true; app.quit(); });
  return true;
});
ipcMain.on('window:theme', (_event, theme: unknown) => {
  const icon = typeof theme === 'string' ? themeIcon(theme) : undefined;
  if (icon && windowRef && !windowRef.isDestroyed()) windowRef.setIcon(icon);
});
ipcMain.handle('dialog:open-directory', async (event, defaultPath?: unknown) => {
  const owner = BrowserWindow.fromWebContents(event.sender);
  const options = { title: '选择工作目录', properties: ['openDirectory' as const], defaultPath: typeof defaultPath === 'string' ? defaultPath : undefined };
  const result = owner ? await dialog.showOpenDialog(owner, options) : await dialog.showOpenDialog(options);
  return result.canceled ? null : result.filePaths[0] ?? null;
});
// Anything Windows would execute on double-click. Opening these from the renderer would let a
// compromised page run programs, so they are shown in Explorer instead.
const RUNNABLE = /\.(exe|com|bat|cmd|ps1|psm1|vbs|vbe|js|jse|wsf|wsh|msi|msp|scr|lnk|url|hta|cpl|jar|reg|appref-ms)$/i;
ipcMain.handle('shell:open-path', async (event, target?: unknown) => {
  if (event.sender !== windowRef?.webContents || typeof target !== 'string' || !path.isAbsolute(target)) return 'invalid path';
  if (RUNNABLE.test(target)) { shell.showItemInFolder(target); return 'revealed'; }
  const error = await shell.openPath(target);
  return error || 'opened';
});
ipcMain.handle('skill-center:token', (event) => {
  if (event.sender !== windowRef?.webContents || event.senderFrame !== event.sender.mainFrame) {
    throw new Error('Skill Center authority is available only to the Atlas main window');
  }
  const frameUrl = event.senderFrame.url;
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  const appFileUrl = pathToFileURL(path.resolve(here, '../../dist/index.html')).href;
  const isTrustedFile = frameUrl === appFileUrl;
  const isTrustedDevOrigin = Boolean(devUrl && new URL(frameUrl).origin === new URL(devUrl).origin);
  if (!isTrustedFile && !isTrustedDevOrigin) {
    throw new Error('Skill Center authority is unavailable to untrusted pages');
  }
  return process.env.ATLAS_SKILL_CENTER_TOKEN;
});

app.whenReady().then(async () => {
  if (!hasSingleInstanceLock) return;
  platformPreferences = loadPlatformPreferences();
  app.setLoginItemSettings({ openAtLogin: platformPreferences.openAtLogin, args: platformPreferences.openAtLogin ? ['--background'] : [] });
  registerPreferredGlobalShortcut();
  // Dedicated system-wide shortcut for the floating composer; it does not replace the user's
  // configurable Atlas focus shortcut. Registration failure leaves the in-app API available.
  globalShortcut.register('Control+Alt+Space', showFloatingComposer);
  if (app.isPackaged) app.setAsDefaultProtocolClient('atlas');
  else if (process.platform === 'win32' || process.platform === 'linux') {
    app.setAsDefaultProtocolClient('atlas', process.execPath, [path.resolve(process.argv[1] ?? '.')]);
  }
  // Atlas draws its own title bar; the default menu's hidden accelerators (Ctrl+W closes the
  // window, Ctrl+R reloads) would fire over the app's own shortcuts.
  Menu.setApplicationMenu(null);
  if (app.isPackaged) {
    process.env.ATLAS_ROOT ??= path.join(process.resourcesPath, 'atlas');
    process.env.ATLAS_DATA_DIR ??= app.getPath('userData');
    process.env.ATLAS_BACKEND_EXECUTABLE ??= path.join(process.resourcesPath, 'atlas', 'backend', 'atlas_backend.exe');
    process.env.ATLAS_NODE_RUNTIME_DIR = path.join(process.resourcesPath, 'atlas', 'runtime', 'node');
    process.env.ATLAS_NODE_RUNTIME_REQUIRED = '1';
    const packageJson = JSON.parse(readFileSync(path.join(app.getAppPath(), 'package.json'), 'utf8'));
    const selectedPackages = [
      '@agentclientprotocol/claude-agent-acp',
      '@agentclientprotocol/codex-acp',
      '@ast-grep/cli',
      '@mariozechner/pi-coding-agent',
      '@playwright/mcp',
      'chrome-devtools-mcp',
    ];
    process.env.ATLAS_NPM_PACKAGE_VERSIONS = JSON.stringify(
      Object.fromEntries(selectedPackages.map((name) => [name, packageJson.dependencies?.[name]])),
    );
  }
  prepareSharedApiToken();
  attachBackendToken();
  lockDownWebviews();
  createTray();
  createWindow();
  startBackend();
  void refreshTrayBackendStatus();
  trayRefreshTimer = setInterval(() => { void refreshTrayBackendStatus(); }, 5_000);
  const initialDeepLink = findAtlasUrl(process.argv);
  if (initialDeepLink) receiveAtlasDeepLink(initialDeepLink);
  // The window may appear after boot already finished (fast external backend): give the
  // renderer the current state once so its startup surfaces resolve immediately.
  windowRef?.webContents.send(BACKEND_STARTUP_CHANNEL, lastProgress);
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
}).catch((error: unknown) => {
  // An exception here used to leave a windowless main process running with no backend.
  const message = error instanceof Error ? error.stack ?? error.message : String(error);
  dialog.showErrorBox('Atlas 启动失败', `Atlas 启动时出错，请把下面的信息发给维护者：\n\n${message}`);
  app.exit(1);
});

let shutdownStarted = false;
let shutdownComplete = false;
app.on('before-quit', (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  if (shutdownStarted) return;
  shutdownStarted = true;
  if (pendingRetry) { clearTimeout(pendingRetry); pendingRetry = null; }
  if (trayRefreshTimer) { clearInterval(trayRefreshTimer); trayRefreshTimer = null; }
  globalShortcut.unregisterAll();
  void stopManagedBackend().finally(() => {
    shutdownComplete = true;
    app.quit();
  });
});

app.on('window-all-closed', () => { /* Atlas stays available from the tray. */ });
