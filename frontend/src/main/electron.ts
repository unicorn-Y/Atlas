import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, nativeImage, powerSaveBlocker, session, shell, Tray } from 'electron';
import { randomBytes, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { setImmediate } from 'node:timers';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ensureBackendRunning, stopManagedBackend } from './backendProcess.js';
import { sourceRoot } from './sourceUpdate.js';
import { applyConfiguredUpdate, checkConfiguredUpdate, defaultUpdateSource, validateUpdateSource, type UpdateSource } from './configuredSourceUpdate.js';
import { exportLocalCrashReport, loadCrashPrivacy, localCrashState, setCrashCapture } from './localCrashReports.js';
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

/** Window/taskbar icon per UI theme (assets/icon/icon-<theme>.png); the exe icon stays 夜航. */
const THEME_ICONS = new Set(['light', 'aurora', 'dark']);
function themeIcon(theme: string): Electron.NativeImage | undefined {
  if (!THEME_ICONS.has(theme)) return undefined;
  const image = nativeImage.createFromPath(path.join(app.getAppPath(), 'assets', 'icon', `icon-${theme}.png`));
  return image.isEmpty() ? undefined : image;
}
let windowRef: BrowserWindow | null = null;
type PlatformPreferences = { alwaysOnTop: boolean; globalShortcut: string | null; trayEnabled: boolean; preventSleepDuringTasks: boolean; updateSource: UpdateSource | null; editorExecutables: Partial<Record<PlatformEditorId, string>> };
const defaultPlatformPreferences: PlatformPreferences = { alwaysOnTop: false, globalShortcut: null, trayEnabled: false, preventSleepDuringTasks: false, updateSource: null, editorExecutables: {} };
let platformPreferences: PlatformPreferences = { ...defaultPlatformPreferences };
const appWindows = new Set<BrowserWindow>();
const conversationWindows = new Map<string, BrowserWindow>();
const windowRoutes = new Map<number, AtlasDeepLink>();
const windowSubscribers = new Set<number>();
const activeTaskWindows = new Set<number>();
let tray: Tray | null = null;
let sleepBlocker: number | null = null;
let quitting = false;
let globalShortcutState: GlobalShortcutState = { accelerator: null, registered: false };
let pendingDeepLinks: AtlasDeepLink[] = [];
let deepLinkSubscriber: Electron.WebContents | null = null;
process.env.ATLAS_SKILL_CENTER_TOKEN ??= randomBytes(32).toString('base64url');
// Proves to the backend that a request comes from this app rather than some web page.
// Only the main process ever sees it: it is attached below, outside the renderer.
process.env.ATLAS_API_TOKEN ??= randomBytes(32).toString('base64url');

/** Session for pages shown in the browser panel. Separate from the app's, so they never get the backend token. */
export const BROWSER_PARTITION = 'persist:atlas-browser';

const SETTINGS_SECTIONS = new Set<AtlasSettingsSection>([
  'models', 'advanced', 'usage', 'limits', 'profiles', 'hooks', 'tools', 'telegram', 'channels',
  'devices', 'localModels', 'shortcuts', 'appearance', 'plugins', 'notifications', 'mcp',
  'skills', 'recipes', 'extensions', 'transfer', 'diagnostics', 'telemetry', 'security', 'commands', 'platform', 'integrations', 'network',
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
      trayEnabled: data.trayEnabled === true,
      preventSleepDuringTasks: data.preventSleepDuringTasks === true,
      updateSource: data.updateSource ? validateUpdateSource(data.updateSource) : null,
      editorExecutables: data.editorExecutables && typeof data.editorExecutables === 'object' ? Object.fromEntries(Object.entries(data.editorExecutables).filter(([id, value]) => Object.hasOwn(IDE_COMMANDS, id) && typeof value === 'string')) : {},
    };
  } catch {
    return { ...defaultPlatformPreferences };
  }
}

function savePlatformPreferences(next: PlatformPreferences): void {
  const target = preferencesPath();
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
  platformPreferences = next;
}

function platformSettingsSnapshot(): PlatformSettingsState {
  return { ...platformPreferences, globalShortcut: { ...globalShortcutState }, sleepBlocked: sleepBlocker !== null, windowCount: appWindows.size };
}

function updateSleepBlocker(): void {
  const needed = platformPreferences.preventSleepDuringTasks && activeTaskWindows.size > 0;
  if (needed && sleepBlocker === null) sleepBlocker = powerSaveBlocker.start('prevent-app-suspension');
  if (!needed && sleepBlocker !== null) { powerSaveBlocker.stop(sleepBlocker); sleepBlocker = null; }
}

function updateTray(): void {
  if (!platformPreferences.trayEnabled) {
    const wasResident = Boolean(tray);
    tray?.destroy(); tray = null;
    if (wasResident && app.isReady()) focusAtlasWindow();
    return;
  }
  if (tray) return;
  const icon = themeIcon('dark');
  if (!icon) throw new Error('未找到托盘图标，无法启用托盘驻留。');
  tray = new Tray(icon);
  tray.setToolTip('Atlas');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示 Atlas', click: focusAtlasWindow },
    { label: '退出 Atlas', click: () => app.quit() },
  ]));
  tray.on('double-click', focusAtlasWindow);
}

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
  if (![...appWindows].some((win) => !win.isDestroyed() && win.webContents === event.sender) || event.senderFrame !== event.sender.mainFrame) {
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
  if (route.type === 'conversation') {
    const win = conversationWindows.get(route.conversationId);
    if (win && !win.isDestroyed()) {
      windowRoutes.set(win.webContents.id, route);
      if (windowSubscribers.has(win.webContents.id)) win.webContents.send('app:deep-link', route);
      if (win.isMinimized()) win.restore();
      win.show(); win.focus();
      return true;
    }
  }
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
  const selectedExecutable = platformPreferences.editorExecutables[editor];
  const executable = selectedExecutable ? validateEditorExecutable(selectedExecutable) : IDE_COMMANDS[editor];
  return new Promise((resolve, reject) => {
    const child = spawn(executable, [canonicalPath], {
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

function validateEditorExecutable(value: string): string {
  if (!path.isAbsolute(value) || value.startsWith('\\\\') || value.includes('\0')) throw new Error('请选择本机编辑器可执行文件。');
  const canonical = realpathSync(value);
  const stat = statSync(canonical);
  if (!stat.isFile() || /\.(cmd|bat|ps1|sh|js|cjs|mjs)$/i.test(canonical)
    || (process.platform === 'win32' ? !/\.exe$/i.test(canonical) : !(stat.mode & 0o111))) {
    throw new Error('必须选择可直接启动的编辑器程序，不能选择脚本或目录。');
  }
  return canonical;
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

function createWindow(conversationId?: string): BrowserWindow {
  if (!conversationId && windowRef && !windowRef.isDestroyed()) {
    windowRef.show();
    windowRef.focus();
    return windowRef;
  }
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1050,
    minHeight: 680,
    backgroundColor: '#faf9f6',
    title: 'Atlas · Agent Workspace',
    icon: themeIcon('dark'),
    titleBarStyle: 'hidden',
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
  appWindows.add(win);
  const webContentsId = win.webContents.id;
  if (!conversationId) windowRef = win;
  else {
    conversationWindows.set(conversationId, win);
    win.setTitle(`Atlas · ${conversationId}`);
    windowRoutes.set(win.webContents.id, { id: randomUUID(), type: 'conversation', conversationId });
  }
  win.setAlwaysOnTop(platformPreferences.alwaysOnTop);

  win.on('maximize', () => win.webContents.send('window:maximize-change', true));
  win.on('unmaximize', () => win.webContents.send('window:maximize-change', false));
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
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return;
    event.preventDefault();
    if (/^atlas:/i.test(url)) receiveAtlasDeepLink(url);
    else if (/^https?:/i.test(url)) void shell.openExternal(url);
  });
  const loadApp = () => {
    if (devUrl) void win.loadURL(devUrl);
    else void win.loadFile(path.join(here, '../../dist/index.html'));
  };
  loadApp();
  // A dead renderer or a failed first paint would otherwise leave an all-white
  // window until the user manually restarts: bring the page back on its own.
  win.webContents.on('render-process-gone', (_event, details) => {
    activeTaskWindows.delete(win.webContents.id); updateSleepBlocker();
    if (details.reason === 'clean-exit') return;
    win.webContents.reload();
  });
  let loadRetries = 0;
  win.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame || code === -3) return; // -3: aborted by a newer navigation
    if (loadRetries >= 5) return;
    loadRetries += 1;
    setTimeout(() => { if (!win.isDestroyed()) loadApp(); }, 500 * loadRetries);
  });
  win.webContents.on('did-finish-load', () => { loadRetries = 0; });
  win.webContents.on('did-start-loading', () => {
    windowSubscribers.delete(win.webContents.id);
    activeTaskWindows.delete(win.webContents.id); updateSleepBlocker();
    if (deepLinkSubscriber === win.webContents) deepLinkSubscriber = null;
  });
  win.on('close', (event) => {
    if (platformPreferences.trayEnabled && tray && !quitting) { event.preventDefault(); win.hide(); }
  });
  win.on('closed', () => {
    appWindows.delete(win);
    windowSubscribers.delete(webContentsId);
    windowRoutes.delete(webContentsId);
    activeTaskWindows.delete(webContentsId); updateSleepBlocker();
    if (conversationId) conversationWindows.delete(conversationId);
    if (windowRef === win) windowRef = null;
    if (deepLinkSubscriber?.id === webContentsId) deepLinkSubscriber = null;
  });
  return win;
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
  const route = windowRoutes.get(event.sender.id);
  if (route) { windowSubscribers.add(event.sender.id); return [route]; }
  deepLinkSubscriber = event.sender;
  const queued = pendingDeepLinks;
  pendingDeepLinks = [];
  return queued;
});
ipcMain.on('deep-link:unsubscribe', (event) => {
  windowSubscribers.delete(event.sender.id);
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
  for (const win of appWindows) if (!win.isDestroyed()) win.setAlwaysOnTop(enabled);
  return platformSettingsSnapshot();
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
ipcMain.handle('platform:select-editor-executable', async (event, editor: unknown) => {
  assertTrustedAppSender(event);
  if (typeof editor !== 'string' || !Object.hasOwn(IDE_COMMANDS, editor)) throw new Error('不支持的编辑器。');
  const owner = BrowserWindow.fromWebContents(event.sender);
  if (!owner) throw new Error('窗口已关闭。');
  const result = await dialog.showOpenDialog(owner, { title: '选择本机编辑器程序', properties: ['openFile'], ...(process.platform === 'win32' ? { filters: [{ name: 'Editor executable', extensions: ['exe'] }] } : {}) });
  if (!result.canceled && result.filePaths[0]) {
    const executable = validateEditorExecutable(result.filePaths[0]);
    savePlatformPreferences({ ...platformPreferences, editorExecutables: { ...platformPreferences.editorExecutables, [editor]: executable } });
  }
  return platformSettingsSnapshot();
});

ipcMain.handle('platform:set-behavior', (event, value: unknown) => {
  assertTrustedAppSender(event);
  if (!value || typeof value !== 'object') throw new Error('平台设置无效。');
  const next = value as { trayEnabled: boolean; preventSleepDuringTasks: boolean };
  if (typeof next.trayEnabled !== 'boolean' || typeof next.preventSleepDuringTasks !== 'boolean') throw new Error('平台设置必须是布尔值。');
  const previous = platformPreferences;
  platformPreferences = { ...previous, ...next };
  try { updateTray(); savePlatformPreferences(platformPreferences); }
  catch (error) { platformPreferences = previous; updateTray(); throw error; }
  updateSleepBlocker();
  return platformSettingsSnapshot();
});
ipcMain.handle('platform:task-activity', (event, active: unknown) => {
  assertTrustedAppSender(event);
  if (typeof active !== 'boolean') throw new Error('任务活动状态无效。');
  if (active) activeTaskWindows.add(event.sender.id); else activeTaskWindows.delete(event.sender.id);
  updateSleepBlocker();
});
ipcMain.handle('platform:conversation-window', (event, conversationId: unknown) => {
  assertTrustedAppSender(event);
  if (typeof conversationId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(conversationId)) throw new Error('会话 ID 无效。');
  const existing = conversationWindows.get(conversationId);
  if (existing && !existing.isDestroyed()) { if (existing.isMinimized()) existing.restore(); existing.show(); existing.focus(); return; }
  if (appWindows.size >= 8) throw new Error('最多打开 8 个 Atlas 窗口。');
  createWindow(conversationId);
});
ipcMain.handle('platform:set-update-source', (event, value: unknown) => {
  assertTrustedAppSender(event);
  savePlatformPreferences({ ...platformPreferences, updateSource: value === null ? null : validateUpdateSource(value) });
  return platformSettingsSnapshot();
});
ipcMain.handle('crash:set-capture', (event, enabled: unknown) => {
  assertTrustedAppSender(event);
  if (typeof enabled !== 'boolean') throw new Error('崩溃采集状态无效。');
  return setCrashCapture(enabled);
});
ipcMain.handle('crash:list', (event) => { assertTrustedAppSender(event); return localCrashState(); });
ipcMain.handle('crash:export', (event, reportId: unknown) => {
  assertTrustedAppSender(event);
  if (typeof reportId !== 'string' || reportId.length > 200) throw new Error('报告 ID 无效。');
  const owner = BrowserWindow.fromWebContents(event.sender);
  if (!owner) throw new Error('窗口已关闭。');
  return exportLocalCrashReport(owner, reportId);
});

ipcMain.on('window:minimize', (event) => { assertTrustedAppSender(event); BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('window:maximize', (event) => {
  assertTrustedAppSender(event);
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win) return;
  if (win.isMaximized()) win.unmaximize();
  else win.maximize();
});
ipcMain.on('window:close', (event) => { assertTrustedAppSender(event); BrowserWindow.fromWebContents(event.sender)?.close(); });
// Source mode (running from a git checkout without the Vite dev server): updates are
// pulled and rebuilt by scripts/atlas-update.mjs instead of reinstalling a package.
const updateRoot = () => (!app.isPackaged && !process.env.VITE_DEV_SERVER_URL ? sourceRoot(app.getAppPath()) : null);
ipcMain.handle('update:check', async (event) => {
  assertTrustedAppSender(event);
  const root = updateRoot();
  if (!root) return { supported: false, available: false, behind: 0, commits: [], blocked: '此安装不是源码模式，没有可用的签名发布 feed。' };
  return checkConfiguredUpdate(root, platformPreferences.updateSource ?? await defaultUpdateSource(root));
});
ipcMain.handle('update:apply', async (event) => {
  assertTrustedAppSender(event);
  const root = updateRoot();
  if (!root) return false;
  const source = platformPreferences.updateSource ?? await defaultUpdateSource(root);
  const status = await checkConfiguredUpdate(root, source);
  if (!status.available || status.blocked || status.error) return false;
  await applyConfiguredUpdate(root, source);
  setImmediate(() => app.quit());
  return true;
});
ipcMain.on('window:theme', (event, theme: unknown) => {
  assertTrustedAppSender(event);
  const icon = typeof theme === 'string' ? themeIcon(theme) : undefined;
  if (icon) BrowserWindow.fromWebContents(event.sender)?.setIcon(icon);
});
ipcMain.handle('dialog:open-directory', async (event, defaultPath?: unknown) => {
  assertTrustedAppSender(event);
  const owner = BrowserWindow.fromWebContents(event.sender);
  const options = { title: '选择工作目录', properties: ['openDirectory' as const], defaultPath: typeof defaultPath === 'string' ? defaultPath : undefined };
  const result = owner ? await dialog.showOpenDialog(owner, options) : await dialog.showOpenDialog(options);
  return result.canceled ? null : result.filePaths[0] ?? null;
});
// Anything Windows would execute on double-click. Opening these from the renderer would let a
// compromised page run programs, so they are shown in Explorer instead.
const RUNNABLE = /\.(exe|com|bat|cmd|ps1|psm1|vbs|vbe|js|jse|wsf|wsh|msi|msp|scr|lnk|url|hta|cpl|jar|reg|appref-ms)$/i;
ipcMain.handle('shell:open-path', async (event, target?: unknown) => {
  assertTrustedAppSender(event);
  if (typeof target !== 'string' || !path.isAbsolute(target)) return 'invalid path';
  if (RUNNABLE.test(target)) { shell.showItemInFolder(target); return 'revealed'; }
  const error = await shell.openPath(target);
  return error || 'opened';
});
ipcMain.handle('skill-center:token', (event) => {
  assertTrustedAppSender(event);
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
  registerPreferredGlobalShortcut();
  try { updateTray(); } catch { platformPreferences.trayEnabled = false; }
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
  // H8 §10.3: the backend boots in parallel with the window instead of blocking it for
  // up to two minutes. Startup progress is broadcast to the renderer (backend:startup-progress),
  // which keeps its "启动中" surfaces until the backend reports ready. A real failure
  // (process exit / cap exceeded) still surfaces the backend log tail and quits.
  let lastProgress: BackendStartupProgress = { phase: 'probing', managed: false, elapsedMs: 0 };
  const forwardProgress = (progress: BackendStartupProgress) => {
    lastProgress = progress;
    for (const win of appWindows) if (!win.isDestroyed()) win.webContents.send(BACKEND_STARTUP_CHANNEL, progress);
  };
  const backendReady = ensureBackendRunning({ onProgress: forwardProgress });
  void backendReady.then(() => loadCrashPrivacy(process.env.ATLAS_API_BASE_URL ?? `http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}`)).catch(() => undefined);
  void backendReady.catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    dialog.showErrorBox('Atlas backend startup failed', `Atlas could not start its backend.\n\n${message}`);
    app.quit();
  });
  attachBackendToken();
  lockDownWebviews();
  createWindow();
  const initialDeepLink = findAtlasUrl(process.argv);
  if (initialDeepLink) receiveAtlasDeepLink(initialDeepLink);
  // The window may appear after boot already finished (fast external backend): give the
  // renderer the current state once so its startup surfaces resolve immediately.
  windowRef?.webContents.send(BACKEND_STARTUP_CHANNEL, lastProgress);
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

let shutdownStarted = false;
let shutdownComplete = false;
app.on('before-quit', (event) => {
  quitting = true;
  if (shutdownComplete) return;
  event.preventDefault();
  if (shutdownStarted) return;
  shutdownStarted = true;
  globalShortcut.unregisterAll();
  tray?.destroy(); tray = null;
  activeTaskWindows.clear(); updateSleepBlocker();
  void stopManagedBackend().finally(() => {
    shutdownComplete = true;
    app.quit();
  });
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin' && !tray) app.quit(); });
