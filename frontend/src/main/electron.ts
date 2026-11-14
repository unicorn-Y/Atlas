import './stdoutSafety.js';
import { app, BrowserWindow, contentTracing, desktopCapturer, dialog, globalShortcut, ipcMain, Menu, nativeImage, powerSaveBlocker, screen, session, shell, systemPreferences, Tray, webContents } from 'electron';
import { randomBytes, randomUUID } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { appendFileSync, chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { setImmediate } from 'node:timers';
import path from 'node:path';
import { injectBackendPort } from './backendPort.js';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ensureBackendRunning, readRunningBackendPid, stopManagedBackend, terminateBackendPid } from './backendProcess.js';
import { checkSourceUpdate, launchSourceUpdater, sourceRoot } from './sourceUpdate.js';
import { checkReleaseUpdate, downloadVerifiedInstaller, launchVerifiedInstaller, setReleasePreference } from './releaseUpdate.js';
import {
  BACKEND_LIFECYCLE_CHANNEL,
  BACKEND_STARTUP_CHANNEL,
  type AtlasDeepLink,
  type AtlasSettingsSection,
  type BackendStartupProgress,
  type BackendLifecycleEvent,
  type CaptureWindowOption,
  type GlobalShortcutState,
  type PlatformEditorId,
  type PlatformSettingsState,
  type RecentScreenshot,
} from '../shared/ipc.js';

const here = path.dirname(fileURLToPath(import.meta.url));
if (process.env.ATLAS_DESKTOP_USER_DATA_DIR) {
  app.setPath('userData', path.resolve(process.env.ATLAS_DESKTOP_USER_DATA_DIR));
}
process.env.ATLAS_LOG_ROOT ??= app.isPackaged
  ? app.getPath('userData')
  : path.resolve(app.getAppPath(), '..');

/** Window/taskbar icon per UI theme (assets/icon/icon-<theme>.png); the exe icon stays 夜航. */
const THEME_ICONS = new Set(['light', 'aurora', 'dark']);
function themeIcon(theme: string): Electron.NativeImage | undefined {
  if (!THEME_ICONS.has(theme)) return undefined;
  const image = nativeImage.createFromPath(path.join(app.getAppPath(), 'assets', 'icon', `icon-${theme}.png`));
  return image.isEmpty() ? undefined : image;
}
let windowRef: BrowserWindow | null = null;
let petOverlayWindow: BrowserWindow | null = null;
let floatingComposerWindow: BrowserWindow | null = null;
let voiceHudWindow: BrowserWindow | null = null;
let taskHudWindow: BrowserWindow | null = null;
let taskHudData = { state: 'idle' as 'running' | 'waiting' | 'idle', summary: '空闲', conversationId: '' };
const pendingVoiceHudResults: string[] = [];
const conversationWindows = new Map<string, BrowserWindow>();
type WindowBounds = { x: number; y: number; width: number; height: number };
type PlatformPreferences = { alwaysOnTop: boolean; globalShortcut: string | null; screenshotShortcut: string | null; voiceShortcut: string | null; openAtLogin: boolean; safeModeOnNextStart: boolean; windowBounds?: WindowBounds };
let platformPreferences: PlatformPreferences = { alwaysOnTop: false, globalShortcut: null, screenshotShortcut: 'Control+Shift+X', voiceShortcut: 'Control+Shift+V', openAtLogin: true, safeModeOnNextStart: false };
let globalShortcutState: GlobalShortcutState = { accelerator: null, registered: false };
let screenshotShortcutState: GlobalShortcutState = { accelerator: 'Control+Shift+X', registered: false };
let voiceShortcutState: GlobalShortcutState = { accelerator: 'Control+Shift+V', registered: false };
let screenshotContext: { conversationId: string; lastInteractionAt: number } = { conversationId: '', lastInteractionAt: 0 };
let floatingComposerContext: { selectedText: string; conversationId?: string } = { selectedText: '' };
const recentScreenshots: RecentScreenshot[] = [];
let keepAwakeEnabled = false;
let keepAwakeBlockerId: number | null = null;
let performanceTraceActive = false;
let runtimeState: 'running' | 'waiting' | 'idle' = 'idle';
let quitActivitySummary = { runningTasks: 0, scheduledTasks: 0 };
let lastBackendLifecycle: BackendLifecycleEvent | null = null;
let backendLifecycleSequence = 0;
let browserAddressShortcutTarget: Electron.WebContents | null = null;
let browserAddressShortcutListener: ((event: Electron.Event, input: Electron.Input) => void) | null = null;
let closePromptOpen = false;
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
let backendSafeModeActive = false;

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

function dataRootPreferencePath(): string {
  return path.join(app.getPath('userData'), 'atlas-data-root.json');
}

function currentDataRoot(): string {
  return path.resolve(process.env.ATLAS_DATA_DIR ?? process.env.ATLAS_ROOT ?? (app.isPackaged ? app.getPath('userData') : path.resolve(app.getAppPath(), '..')));
}

function saveDesktopCrashReport(reason: string, details: Record<string, unknown>): void {
  try {
    const directory = path.join(currentDataRoot(), 'data', 'crash-reports');
    mkdirSync(directory, { recursive: true });
    const report = { id: randomUUID(), created_at: new Date().toISOString(), reason: reason.slice(0, 300),
      app_version: app.getVersion(), platform: process.platform, electron: process.versions.electron,
      details: Object.fromEntries(Object.entries(details).filter(([key]) => !/(key|token|secret|password|credential)/i.test(key))) };
    writeFileSync(path.join(directory, `crash-${report.id}.json`), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  } catch { /* a crash archive must never prevent window recovery or shutdown */ }
}

function applySavedDataRoot(): void {
  try {
    const saved = JSON.parse(readFileSync(dataRootPreferencePath(), 'utf8')) as { current_root?: unknown };
    if (typeof saved.current_root === 'string' && path.isAbsolute(saved.current_root) && existsSync(saved.current_root)) {
      process.env.ATLAS_DATA_DIR = path.resolve(saved.current_root);
    }
  } catch { /* first launch uses the configured default data root */ }
}

function loadPlatformPreferences(): PlatformPreferences {
  try {
    const data = JSON.parse(readFileSync(preferencesPath(), 'utf8')) as Record<string, unknown>;
    return {
      alwaysOnTop: data.alwaysOnTop === true,
      globalShortcut: typeof data.globalShortcut === 'string' ? data.globalShortcut : null,
      screenshotShortcut: typeof data.screenshotShortcut === 'string' ? data.screenshotShortcut : 'Control+Shift+X',
      voiceShortcut: typeof data.voiceShortcut === 'string' ? data.voiceShortcut : 'Control+Shift+V',
      openAtLogin: data.openAtLogin !== false,
      safeModeOnNextStart: data.safeModeOnNextStart === true,
      ...(isWindowBounds(data.windowBounds) ? { windowBounds: data.windowBounds } : {}),
    };
  } catch {
    return { alwaysOnTop: false, globalShortcut: null, screenshotShortcut: 'Control+Shift+X', voiceShortcut: 'Control+Shift+V', openAtLogin: true, safeModeOnNextStart: false };
  }
}

function isWindowBounds(value: unknown): value is WindowBounds {
  if (!value || typeof value !== 'object') return false;
  const bounds = value as Record<string, unknown>;
  return ['x', 'y', 'width', 'height'].every((key) => typeof bounds[key] === 'number' && Number.isFinite(bounds[key]))
    && Number(bounds.width) >= 1050 && Number(bounds.height) >= 680;
}

function restoredWindowBounds(): WindowBounds {
  const saved = platformPreferences.windowBounds;
  if (!saved) return { x: 0, y: 0, width: 1440, height: 920 };
  const overlapsDisplay = screen.getAllDisplays().some(({ workArea }) =>
    saved.x < workArea.x + workArea.width && saved.x + saved.width > workArea.x
      && saved.y < workArea.y + workArea.height && saved.y + saved.height > workArea.y);
  return overlapsDisplay ? saved : { x: 0, y: 0, width: 1440, height: 920 };
}

function savePlatformPreferences(next: PlatformPreferences): void {
  const target = preferencesPath();
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
  platformPreferences = next;
}

function platformSettingsSnapshot(): PlatformSettingsState {
  return { alwaysOnTop: platformPreferences.alwaysOnTop, openAtLogin: platformPreferences.openAtLogin, globalShortcut: { ...globalShortcutState }, screenshotShortcut: { ...screenshotShortcutState }, voiceShortcut: { ...voiceShortcutState } };
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
    { label: '以安全模式重启', click: () => { void restartBackendNow('tray_safe_mode', true); } },
    ...(platformPreferences.safeModeOnNextStart ? [{ label: '正常重启', click: () => { void restartBackendNow('tray_normal_mode', false); } }] : []),
    ...(!platformPreferences.safeModeOnNextStart ? [{ label: '重启后台', click: () => { void restartBackendNow('tray_menu', false); } }] : []),
    { label: '查看日志', click: () => { void shell.openPath(backendLogPath()); } },
    { type: 'separator' },
    { label: '开机自启', type: 'checkbox', checked: platformPreferences.openAtLogin, click: (item) => setOpenAtLogin(item.checked) },
    { type: 'separator' },
    { label: '退出 Atlas', click: () => { void requestExplicitQuit(); } },
  ]));
}

export function createTray(): void {
  if (trayRef) return;
  const image = nativeImage.createFromPath(path.join(app.getAppPath(), 'assets', 'icon', 'icon-dark.png'));
  trayRef = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image);
  trayRef.setToolTip('Atlas · 空闲');
  trayRef.on('double-click', focusAtlasWindow);
  updateRuntimeState(runtimeState);
  buildTrayMenu();
}

function updateRuntimeState(state: 'running' | 'waiting' | 'idle'): void {
  runtimeState = state;
  taskHudData = { ...taskHudData, state, summary: state === 'running' ? (taskHudData.summary || '任务运行中') : state === 'waiting' ? '等待输入' : '空闲' };
  if (taskHudWindow && !taskHudWindow.isDestroyed()) taskHudWindow.webContents.send('task-hud:data', taskHudData);
  if (petOverlayWindow && !petOverlayWindow.isDestroyed()) petOverlayWindow.webContents.send('pet-overlay:state', state);
  const running = state === 'running' && keepAwakeEnabled;
  if (running && (keepAwakeBlockerId === null || !powerSaveBlocker.isStarted(keepAwakeBlockerId))) {
    keepAwakeBlockerId = powerSaveBlocker.start('prevent-app-suspension');
  } else if (!running && keepAwakeBlockerId !== null) {
    if (powerSaveBlocker.isStarted(keepAwakeBlockerId)) powerSaveBlocker.stop(keepAwakeBlockerId);
    keepAwakeBlockerId = null;
  }
  const label = state === 'running' ? '运行中' : state === 'waiting' ? '等待你处理' : '空闲';
  if (trayRef) {
    const color = state === 'running' ? '#3e63dd' : state === 'waiting' ? '#e2a336' : '#30a46c';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#20232b"/><path d="M8 23 15.8 7 24 23h-4l-4.2-8.4L12 23z" fill="white"/><circle cx="25" cy="7" r="5" fill="${color}" stroke="#fff" stroke-width="1.5"/></svg>`;
    trayRef.setImage(nativeImage.createFromDataURL(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`));
    trayRef.setToolTip(`Atlas · ${label}`);
  }
  buildTrayMenu();
}

function toggleTaskHud(): boolean {
  if (taskHudWindow && !taskHudWindow.isDestroyed()) {
    taskHudWindow.setIgnoreMouseEvents(false);
    taskHudWindow.webContents.send('task-hud:click-through-state', false);
    if (taskHudWindow.isVisible()) taskHudWindow.hide(); else taskHudWindow.showInactive();
    return taskHudWindow.isVisible();
  }
  const { workArea } = screen.getPrimaryDisplay();
  const win = new BrowserWindow({
    x: Math.max(workArea.x, workArea.x + workArea.width - 500), y: workArea.y + 24,
    width: 460, height: 92, show: false, frame: false, transparent: true,
    resizable: false, movable: true, focusable: true, skipTaskbar: true,
    alwaysOnTop: true, hasShadow: true,
    webPreferences: { preload: path.join(here, '../preload/index.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  taskHudWindow = win;
  win.setAlwaysOnTop(true, 'floating');
  win.on('closed', () => { if (taskHudWindow === win) taskHudWindow = null; });
  win.webContents.on('did-finish-load', () => win.webContents.send('task-hud:data', taskHudData));
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) void win.loadURL(new URL('/task-hud.html', devUrl).href);
  else void win.loadFile(path.join(here, '../../dist/task-hud.html'));
  win.showInactive();
  return true;
}

function activityDetail(): string {
  const lines = [
    `本地运行任务：${quitActivitySummary.runningTasks} 个（退出会中断仍在运行的任务）`,
    `已启用排期任务：${quitActivitySummary.scheduledTasks} 个（退出期间不会触发，Atlas 下次启动后恢复）`,
  ];
  return lines.join('\n');
}

function publishBackendLifecycle(event: Omit<BackendLifecycleEvent, 'timestamp' | 'sequence'>): void {
  lastBackendLifecycle = { ...event, sequence: ++backendLifecycleSequence, timestamp: new Date().toISOString() } satisfies BackendLifecycleEvent;
  windowRef?.webContents.send(BACKEND_LIFECYCLE_CHANNEL, lastBackendLifecycle);
}

async function requestExplicitQuit(owner?: BrowserWindow | null): Promise<boolean> {
  publishBackendLifecycle({ kind: 'quit-inspection', ...quitActivitySummary });
  const hasActivity = quitActivitySummary.runningTasks > 0 || quitActivitySummary.scheduledTasks > 0;
  if (hasActivity) {
    const options = {
      type: 'warning' as const,
      title: '退出 Atlas？',
      message: '退出会停止本地活动并暂停排期任务。',
      detail: activityDetail(),
      buttons: ['退出并中断任务', '取消'],
      defaultId: 1,
      cancelId: 1,
      noLink: true,
    };
    const result = owner && !owner.isDestroyed()
      ? await dialog.showMessageBox(owner, options)
      : await dialog.showMessageBox(options);
    if (result.response !== 0) return false;
  }
  explicitQuit = true;
  app.quit();
  return true;
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
  void ensureBackendRunning({ onProgress: publishProgress, safeMode: platformPreferences.safeModeOnNextStart }).then(() => {
    if (attempt !== backendAttempt) return;
    backendSafeModeActive = platformPreferences.safeModeOnNextStart;
    retryCount = 0;
    publishBackendLifecycle({ kind: 'ready' });
  }).catch((error: unknown) => {
    if (attempt !== backendAttempt || explicitQuit) return;
    backendSafeModeActive = false;
    const message = error instanceof Error ? error.message : String(error);
    const detail = message.slice(-6000);
    publishBackendLifecycle({ kind: 'fatal', detail });
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

function togglePetOverlay(): boolean {
  if (petOverlayWindow && !petOverlayWindow.isDestroyed()) {
    petOverlayWindow.close();
    return false;
  }
  const area = screen.getPrimaryDisplay().workArea;
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  const win = new BrowserWindow({
    x: area.x + area.width - 164,
    y: area.y + area.height - 190,
    width: 148,
    height: 180,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(here, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  petOverlayWindow = win;
  const overlayUrl = devUrl
    ? new URL('pet-overlay.html', devUrl.endsWith('/') ? devUrl : `${devUrl}/`).href
    : pathToFileURL(path.resolve(here, '../../dist/pet-overlay.html')).href;
  const allowed = (target: string) => devUrl
    ? (() => { try { const url = new URL(target); return url.origin === new URL(devUrl).origin && url.pathname.endsWith('/pet-overlay.html'); } catch { return false; } })()
    : target.split('#')[0] === overlayUrl;
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, target) => { if (!allowed(target)) event.preventDefault(); });
  win.webContents.on('did-finish-load', () => win.webContents.send('pet-overlay:state', runtimeState));
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => { if (petOverlayWindow === win) petOverlayWindow = null; });
  void win.loadURL(overlayUrl);
  return true;
}

function showFloatingComposer(context?: { selectedText?: string; conversationId?: string }): void {
  if (!app.isReady()) return;
  floatingComposerContext = {
    selectedText: typeof context?.selectedText === 'string' ? context.selectedText.slice(0, 12_000) : '',
    conversationId: typeof context?.conversationId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(context.conversationId)
      ? context.conversationId : screenshotContext.conversationId || undefined,
  };
  if (!floatingComposerWindow || floatingComposerWindow.isDestroyed()) {
    const devUrl = process.env.VITE_DEV_SERVER_URL;
    const win = new BrowserWindow({
      width: 720,
      height: 640,
      minWidth: 420,
      minHeight: 320,
      maxWidth: 900,
      maxHeight: 900,
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
    win.webContents.on('did-finish-load', () => {
      if (!win.isDestroyed()) win.webContents.send('floating-composer:context', floatingComposerContext);
    });
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
    floatingComposerWindow.webContents.send('floating-composer:context', floatingComposerContext);
    floatingComposerWindow.show();
    floatingComposerWindow.focus();
  }
}

function openConversationWindow(conversationId?: string, newSession = false): void {
  if (conversationId && !/^[A-Za-z0-9_-]{1,128}$/.test(conversationId)) throw new Error('无效的会话 ID。');
  const existing = conversationId ? conversationWindows.get(conversationId) : undefined;
  if (existing && !existing.isDestroyed()) {
    if (existing.isMinimized()) existing.restore();
    existing.show(); existing.focus();
    return;
  }
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  const win = new BrowserWindow({
    width: 1180, height: 820, minWidth: 760, minHeight: 560,
    title: 'Atlas · 对话', backgroundColor: '#faf9f6', show: false,
    webPreferences: {
      preload: path.join(here, '../preload/index.cjs'),
      contextIsolation: true, nodeIntegration: false, sandbox: true, webviewTag: true,
    },
  });
  if (conversationId) conversationWindows.set(conversationId, win);
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    const isApp = devUrl ? (() => { try { return new URL(url).origin === new URL(devUrl).origin; } catch { return false; } })()
      : url.split('?')[0].split('#')[0] === pathToFileURL(path.resolve(here, '../../dist/index.html')).href;
    if (!isApp) { event.preventDefault(); if (/^https?:/i.test(url)) void shell.openExternal(url); }
  });
  if (devUrl) {
    const target = new URL(devUrl);
    if (conversationId) target.searchParams.set('conversationId', conversationId);
    else if (newSession) target.searchParams.set('newSession', '1');
    void win.loadURL(target.href);
  } else void win.loadFile(path.join(here, '../../dist/index.html'), { query: conversationId ? { conversationId } : newSession ? { newSession: '1' } : {} });
  win.once('ready-to-show', () => { win.show(); win.focus(); });
  win.on('closed', () => { if (conversationId && conversationWindows.get(conversationId) === win) conversationWindows.delete(conversationId); });
}

function openSideChatWindow(conversationId: string, initialQuestion?: string): void {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(conversationId)) throw new Error('无效的会话 ID。');
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  const win = new BrowserWindow({
    width: 720, height: 680, minWidth: 480, minHeight: 420,
    title: 'Atlas · 旁聊', backgroundColor: '#faf9f6', show: false,
    webPreferences: { preload: path.join(here, '../preload/index.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true, webviewTag: true },
  });
  const query = `sideChat=1&conversationId=${encodeURIComponent(conversationId)}${initialQuestion ? `&question=${encodeURIComponent(initialQuestion.slice(0, 12000))}` : ''}`;
  const url = devUrl ? `${devUrl}/?${query}` : `file://${path.join(here, '../renderer/index.html')}?${query}`;
  void win.loadURL(url);
  win.once('ready-to-show', () => { win.show(); win.focus(); });
}

export function createApplicationMenu(): void {
  const mac = process.platform === 'darwin';
  const menu = Menu.buildFromTemplate([
    ...(mac ? [{ label: app.name, submenu: [{ role: 'about' as const }, { type: 'separator' as const }, { role: 'quit' as const }] }] : []),
    { label: '文件', submenu: [
      { label: '新建窗口', accelerator: 'CommandOrControl+Shift+N', click: () => openConversationWindow() },
      { label: '新会话并在新窗口打开', accelerator: 'CommandOrControl+Alt+N', click: () => openConversationWindow(undefined, true) },
      { type: 'separator' }, { label: '关闭当前窗口', click: () => BrowserWindow.getFocusedWindow()?.close() },
    ] },
    { label: '编辑', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: '视图', submenu: [{ label: '刷新窗口', click: () => BrowserWindow.getFocusedWindow()?.webContents.reload() }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
    { label: '帮助', submenu: [{ label: '窗口关闭行为', click: () => {
      const options: Electron.MessageBoxOptions = {
        type: 'info', title: 'Atlas 窗口行为',
        message: '关闭独立窗口只关闭该窗口；会话仍保存在历史记录中。关闭主窗口会收起到系统托盘，退出 Atlas 请使用托盘菜单中的“退出”。',
      };
      const focused = BrowserWindow.getFocusedWindow();
      void (focused ? dialog.showMessageBox(focused, options) : dialog.showMessageBox(options));
    } }] },
  ]);
  Menu.setApplicationMenu(menu);
}

function tryRegisterGlobalShortcut(accelerator: string | null): GlobalShortcutState {
  if (!accelerator) return { accelerator: null, registered: false };
  const invalid = validateGlobalAccelerator(accelerator);
  if (invalid) return { accelerator, registered: false, error: invalid };
  try {
    const registered = globalShortcut.register(accelerator, showFloatingComposer);
    return registered
      ? { accelerator, registered: true }
      : { accelerator, registered: false, error: '系统未能注册此快捷键，可能已被其他应用占用。' };
  } catch {
    return { accelerator, registered: false, error: '系统未能注册此快捷键。' };
  }
}

function registerPreferredGlobalShortcut(): void {
  globalShortcutState = tryRegisterGlobalShortcut(platformPreferences.globalShortcut);
  screenshotShortcutState = tryRegisterScreenshotShortcut(platformPreferences.screenshotShortcut);
  voiceShortcutState = tryRegisterVoiceShortcut(platformPreferences.voiceShortcut);
}

function tryRegisterVoiceShortcut(accelerator: string | null): GlobalShortcutState {
  if (!accelerator) return { accelerator: null, registered: false };
  const invalid = validateGlobalAccelerator(accelerator);
  if (invalid) return { accelerator, registered: false, error: invalid };
  try {
    const registered = globalShortcut.register(accelerator, triggerVoiceShortcut);
    return registered ? { accelerator, registered: true } : { accelerator, registered: false, error: '系统未能注册语音快捷键，可能已被其他应用占用。' };
  } catch { return { accelerator, registered: false, error: '系统未能注册语音快捷键。' }; }
}

async function triggerVoiceShortcut(): Promise<void> {
  if (voiceHudWindow && !voiceHudWindow.isDestroyed() && voiceHudWindow.isVisible()) {
    voiceHudWindow.webContents.send('voice-hud:stop');
    voiceHudWindow.hide();
    return;
  }
  if (!voiceHudWindow || voiceHudWindow.isDestroyed()) {
    const { workArea } = screen.getPrimaryDisplay();
    voiceHudWindow = new BrowserWindow({
      x: Math.max(workArea.x, workArea.x + workArea.width - 484), y: workArea.y + 24,
      width: 460, height: 80, show: false, frame: false, transparent: true,
      resizable: false, movable: true, focusable: false, skipTaskbar: true,
      alwaysOnTop: true, hasShadow: false,
      webPreferences: { preload: path.join(here, '../preload/index.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
    voiceHudWindow.setAlwaysOnTop(true, 'floating');
    voiceHudWindow.on('closed', () => { voiceHudWindow = null; });
    const devUrl = process.env.VITE_DEV_SERVER_URL;
    if (devUrl) void voiceHudWindow.loadURL(new URL('/voice-hud.html', devUrl).href);
    else void voiceHudWindow.loadFile(path.join(here, '../../dist/voice-hud.html'));
  }
  // The HUD owns the one ASR stream for a global shortcut. Stop any Composer
  // dictation first so the shortcut can never open two microphones at once.
  if (windowRef && !windowRef.isDestroyed()) {
    const main = windowRef;
    await new Promise<void>((resolve) => {
      const finish = () => {
        clearTimeout(timer);
        ipcMain.removeListener('app:voice-hotkey-stopped', finish);
        resolve();
      };
      const timer = setTimeout(finish, 1800);
      ipcMain.once('app:voice-hotkey-stopped', finish);
      if (!main.isDestroyed()) main.webContents.send('app:voice-hotkey-stop');
      else finish();
    });
  }
  const win = voiceHudWindow;
  if (win.webContents.isLoading()) win.webContents.once('did-finish-load', () => { if (!win.isDestroyed()) { win.showInactive(); win.webContents.send('voice-hud:start'); } });
  else { win.showInactive(); win.webContents.send('voice-hud:start'); }
}

function disposeVoiceHud(): void {
  if (voiceHudWindow && !voiceHudWindow.isDestroyed()) voiceHudWindow.destroy();
  voiceHudWindow = null;
}

function tryRegisterScreenshotShortcut(accelerator: string | null): GlobalShortcutState {
  if (!accelerator) return { accelerator: null, registered: false };
  const invalid = validateGlobalAccelerator(accelerator);
  if (invalid) return { accelerator, registered: false, error: invalid };
  try {
    const registered = globalShortcut.register(accelerator, () => { void captureSessionScreenshot(); });
    return registered ? { accelerator, registered: true }
      : { accelerator, registered: false, error: '系统未能注册截图快捷键，可能已被其他应用占用。' };
  } catch {
    return { accelerator, registered: false, error: '系统未能注册截图快捷键。' };
  }
}

async function captureSessionScreenshot(): Promise<void> {
  const { conversationId, lastInteractionAt } = screenshotContext;
  const targetWindow = windowForConversation(conversationId);
  if (!conversationId || Date.now() - lastInteractionAt > 60_000 || !targetWindow || targetWindow.isDestroyed()) return;
  try {
    const access = getSystemAccessStatus();
    if (process.platform === 'darwin' && access.screen !== 'granted') {
      targetWindow.webContents.send('app:session-screenshot-error', access.screen === 'denied' || access.screen === 'restricted' ? '系统拒绝了屏幕录制权限。请在系统设置 → 隐私与安全性 → 屏幕录制中允许 Atlas，然后重新尝试。' : '尚未授予屏幕录制权限，请先在系统设置中允许 Atlas。');
      return;
    }
    const cursor = screen.getCursorScreenPoint();
    const display = screen.getDisplayNearestPoint(cursor);
    const sources = await desktopCapturer.getSources({
      types: ['screen'], thumbnailSize: { width: display.size.width, height: display.size.height },
    });
    const source = sources.find((item) => item.display_id === String(display.id)) ?? sources[0];
    if (source?.thumbnail && !source.thumbnail.isEmpty()) {
      deliverScreenshot(screenshotDataUrl(source.thumbnail), source.name || '屏幕截图', conversationId);
    } else {
      targetWindow.webContents.send('app:session-screenshot-error', '系统没有返回可捕获的屏幕画面。请检查屏幕录制权限与显示器状态，然后在设置 → 电脑操控中点“重新捕获截图”。');
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    targetWindow.webContents.send('app:session-screenshot-error', /permission|denied|not allowed|屏幕录制/i.test(detail)
      ? `系统拒绝了屏幕捕获权限：${detail}。请检查系统隐私设置后重试。`
      : `截图捕获失败：${detail}。请重试；若持续失败，请检查显示器与 Atlas 日志。`);
    console.error('Session screenshot capture failed:', error);
  }
}

function deliverScreenshot(dataUrl: string, title: string, conversationId: string): RecentScreenshot {
  pruneRecentScreenshots();
  const screenshot: RecentScreenshot = { id: randomUUID(), title: title.slice(0, 160), capturedAt: Date.now(), dataUrl };
  recentScreenshots.unshift(screenshot);
  recentScreenshots.splice(8);
  const target = windowForConversation(conversationId);
  if (target && !target.isDestroyed()) target.webContents.send('app:session-screenshot', dataUrl, conversationId);
  return screenshot;
}

function screenshotDataUrl(image: Electron.NativeImage): string {
  const resized = image.resize({ width: 1600, height: 1000, quality: 'good' });
  return `data:image/jpeg;base64,${resized.toJPEG(82).toString('base64')}`;
}

function windowForConversation(conversationId: string): BrowserWindow | null {
  return BrowserWindow.getAllWindows().find((item) => !item.isDestroyed() && item.webContents.getURL().includes(encodeURIComponent(conversationId))) ?? windowRef;
}

function pruneRecentScreenshots(): void {
  const cutoff = Date.now() - 30 * 60 * 1000;
  for (let index = recentScreenshots.length - 1; index >= 0; index -= 1) {
    if (recentScreenshots[index].capturedAt < cutoff) recentScreenshots.splice(index, 1);
  }
  recentScreenshots.splice(8);
}

function getSystemAccessStatus() {
  if (process.platform === 'darwin') {
    let screenStatus = 'unknown';
    let accessibility = 'unknown';
    try { screenStatus = systemPreferences.getMediaAccessStatus('screen'); } catch { /* unavailable on older Electron */ }
    try { accessibility = systemPreferences.isTrustedAccessibilityClient(false) ? 'granted' : 'not-determined'; } catch { /* macOS only */ }
    return { platform: process.platform, screen: screenStatus, accessibility, supported: true };
  }
  return { platform: process.platform, screen: 'not-required', accessibility: 'not-required', supported: false };
}

function setScreenshotShortcut(accelerator: string | null): GlobalShortcutState {
  if (accelerator !== null) {
    const invalid = validateGlobalAccelerator(accelerator);
    if (invalid) return { accelerator, registered: false, error: invalid };
  }
  const previous = platformPreferences.screenshotShortcut;
  const next = { ...platformPreferences, screenshotShortcut: accelerator };
  savePlatformPreferences(next);
  if (previous && screenshotShortcutState.registered) globalShortcut.unregister(previous);
  screenshotShortcutState = tryRegisterScreenshotShortcut(accelerator);
  return { ...screenshotShortcutState };
}

function setVoiceShortcut(accelerator: string | null): GlobalShortcutState {
  if (accelerator !== null) { const invalid = validateGlobalAccelerator(accelerator); if (invalid) return { accelerator, registered: false, error: invalid }; }
  const previous = platformPreferences.voiceShortcut;
  savePlatformPreferences({ ...platformPreferences, voiceShortcut: accelerator });
  if (previous && voiceShortcutState.registered) globalShortcut.unregister(previous);
  voiceShortcutState = tryRegisterVoiceShortcut(accelerator);
  return { ...voiceShortcutState };
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

export function parseAtlasDeepLink(raw: string): AtlasDeepLink | null {
  try {
    const url = new URL(raw);
    if (url.protocol !== 'atlas:' || url.username || url.password || url.port || url.hash) return null;
    const segments = url.pathname.split('/').filter(Boolean).map((segment) => decodeURIComponent(segment));
    if (url.hostname === 'share' && segments.length === 1 && /^[A-Za-z0-9_-]{20,128}$/.test(segments[0])) {
      const source = url.searchParams.get('source') ?? '';
      const shared = new URL(source);
      if (url.searchParams.size !== 1 || !['http:', 'https:'].includes(shared.protocol) || shared.username || shared.password
          || !shared.pathname.endsWith(`/api/shared/${segments[0]}`)) return null;
      return { id: randomUUID(), type: 'share-import', token: segments[0], shareUrl: source };
    }
    if (segments.length !== 1) return null;
    if (url.hostname === 'conversation' && /^[A-Za-z0-9_-]{1,128}$/.test(segments[0])) {
      const allowedParams = [...url.searchParams.keys()];
      if (allowedParams.some((key) => key !== 'draft') || allowedParams.length > 1) return null;
      const draft = url.searchParams.get('draft');
      if (draft !== null && draft.length > 12000) return null;
      return { id: randomUUID(), type: 'conversation', conversationId: segments[0], ...(draft !== null ? { draft } : {}) };
    }
    if (!url.search && url.hostname === 'settings' && SETTINGS_SECTIONS.has(segments[0] as AtlasSettingsSection)) {
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
      contents.setZoomMode('manual');
      contents.on('before-input-event', (event, input) => {
        if ((input.control || input.meta) && input.key.toLowerCase() === 'f') {
          event.preventDefault();
          if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('browser:find');
          return;
        }
        if (input.type === 'keyDown' && (input.control || input.meta)) {
          const key = input.key.toLowerCase();
          const action = key === '+' || key === '=' || key === 'add' ? 'in'
            : key === '-' || key === '_' || key === 'subtract' ? 'out'
              : key === '0' ? 'reset' : null;
          if (action) {
            event.preventDefault();
            if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('browser:zoom', {
              webContentsId: contents.id, action,
            });
          }
        }
      });
      contents.on('zoom-changed', (event, direction) => {
        event.preventDefault();
        if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('browser:zoom', {
          webContentsId: contents.id, action: direction === 'in' ? 'in' : 'out',
        });
      });
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

export async function recoverRendererCrash(win: BrowserWindow, details: { reason: string; exitCode: number }): Promise<void> {
  if (details.reason === 'clean-exit') return;
  saveDesktopCrashReport('renderer-process-gone', { ...details, processType: 'renderer' });
  try {
    const { response } = await dialog.showMessageBox(win, {
      type: 'error', title: 'Atlas 页面意外退出',
      message: '请选择恢复方式。安全模式会禁用全部插件、扩展和 MCP，并重新启动后端。',
      buttons: ['重新加载', '禁用全部插件并重启', '稍后'], defaultId: 0, cancelId: 2,
    });
    if (response === 2) return;
    if (response === 1) await restartBackendNow('renderer_crash_safe_mode', true);
    if (!win.isDestroyed()) win.webContents.reload();
  } catch {
    saveDesktopCrashReport('renderer-recovery-failed', { action: 'reload-or-safe-mode-restart' });
    if (!win.isDestroyed()) win.webContents.reload();
  }
}

function createWindow() {
  if (windowRef && !windowRef.isDestroyed()) {
    windowRef.show();
    windowRef.focus();
    return;
  }
  const bounds = restoredWindowBounds();
  windowRef = new BrowserWindow({
    ...bounds,
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
  let boundsSaveTimer: NodeJS.Timeout | undefined;
  const persistBounds = () => {
    if (!windowRef || windowRef.isDestroyed() || windowRef.isMaximized() || windowRef.isMinimized()) return;
    clearTimeout(boundsSaveTimer);
    boundsSaveTimer = setTimeout(() => {
      if (!windowRef || windowRef.isDestroyed() || windowRef.isMaximized() || windowRef.isMinimized()) return;
      const current = windowRef.getBounds();
      savePlatformPreferences({ ...platformPreferences, windowBounds: { x: current.x, y: current.y, width: current.width, height: current.height } });
    }, 250);
  };
  windowRef.on('move', persistBounds);
  windowRef.on('resize', persistBounds);

  windowRef.on('maximize', () => windowRef?.webContents.send('window:maximize-change', true));
  windowRef.on('unmaximize', () => windowRef?.webContents.send('window:maximize-change', false));
  windowRef.on('enter-full-screen', () => windowRef?.webContents.send('window:fullscreen-change', true));
  windowRef.on('leave-full-screen', () => windowRef?.webContents.send('window:fullscreen-change', false));
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
  // Recover a dead renderer with a reload or a plugin-disabled restart.
  win.webContents.on('render-process-gone', (_event, details) => { void recoverRendererCrash(win, details); });
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
    if (hasSelection) items.push({ type: 'separator' }, {
      label: '随手写 / 改写选中文字',
      click: () => showFloatingComposer({ selectedText: selectionText.trim(), conversationId: screenshotContext.conversationId }),
    });
    Menu.buildFromTemplate(items).popup({ window: win });
  });
  win.webContents.on('did-start-loading', () => {
    if (deepLinkSubscriber === win.webContents) deepLinkSubscriber = null;
  });
  win.webContents.on('did-finish-load', () => {
    win.webContents.send(BACKEND_STARTUP_CHANNEL, lastProgress);
    for (const transcript of pendingVoiceHudResults.splice(0)) {
      win.webContents.send('app:voice-hud-result', transcript);
    }
  });
  windowRef.on('close', (event) => {
    if (explicitQuit) return;
    event.preventDefault();
    disposeVoiceHud();
    if (quitActivitySummary.runningTasks === 0 && quitActivitySummary.scheduledTasks === 0) {
      windowRef?.hide();
      return;
    }
    if (closePromptOpen) return;
    closePromptOpen = true;
    const owner = windowRef;
    if (!owner || owner.isDestroyed()) { closePromptOpen = false; return; }
    void dialog.showMessageBox(owner, {
      type: 'warning',
      title: '关闭 Atlas',
      message: '当前仍有本地运行或排期任务。',
      detail: activityDetail(),
      buttons: ['继续后台运行', '退出并中断任务', '取消'],
      defaultId: 0,
      cancelId: 2,
      noLink: true,
    }).then(({ response }) => {
      closePromptOpen = false;
      if (response === 0) windowRef?.hide();
      else if (response === 1) { explicitQuit = true; app.quit(); }
    }).catch(() => { closePromptOpen = false; });
  });
  windowRef.on('closed', () => {
    windowRef = null;
    disposeVoiceHud();
  });
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
ipcMain.handle('conversation:open-window', (event, conversationId?: unknown, newSession?: unknown) => {
  assertTrustedAppSender(event);
  if (conversationId !== undefined && typeof conversationId !== 'string') throw new Error('无效的会话 ID。');
  openConversationWindow(conversationId as string | undefined, newSession === true);
});
ipcMain.handle('app:focus-window', (event) => {
  assertTrustedAppSender(event);
  focusAtlasWindow();
});
ipcMain.handle('pet-overlay:toggle', (event) => {
  assertTrustedAppSender(event);
  return togglePetOverlay();
});
ipcMain.handle('side-chat:open-window', (event, conversationId: unknown, initialQuestion?: unknown) => {
  assertTrustedAppSender(event);
  if (typeof conversationId !== 'string') throw new Error('无效的会话 ID。');
  if (initialQuestion !== undefined && typeof initialQuestion !== 'string') throw new Error('无效的旁聊问题。');
  openSideChatWindow(conversationId, initialQuestion as string | undefined);
});
ipcMain.handle('screenshot:list-windows', async (event): Promise<CaptureWindowOption[]> => {
  assertTrustedAppSender(event);
  const sources = await desktopCapturer.getSources({ types: ['window'], thumbnailSize: { width: 360, height: 220 }, fetchWindowIcons: true });
  return sources.filter((source) => source.name.trim() && !source.thumbnail.isEmpty()).map((source) => ({
    id: source.id, title: source.name.slice(0, 160), thumbnail: source.thumbnail.toDataURL(),
  }));
});
ipcMain.handle('screenshot:capture-window', async (event, sourceId: unknown, conversationId: unknown): Promise<RecentScreenshot> => {
  assertTrustedAppSender(event);
  if (typeof sourceId !== 'string' || sourceId.length > 512 || typeof conversationId !== 'string' || (conversationId && !/^[A-Za-z0-9_-]{1,128}$/.test(conversationId))) {
    throw new Error('请选择有效的窗口和目标会话。');
  }
  const sources = await desktopCapturer.getSources({ types: ['window'], thumbnailSize: { width: 1920, height: 1200 } });
  const source = sources.find((item) => item.id === sourceId);
  if (!source || source.thumbnail.isEmpty()) throw new Error('所选窗口已关闭或系统未返回截图。');
  const dataUrl = screenshotDataUrl(source.thumbnail);
  pruneRecentScreenshots();
  const screenshot: RecentScreenshot = { id: randomUUID(), title: source.name.slice(0, 160), capturedAt: Date.now(), dataUrl };
  recentScreenshots.unshift(screenshot); recentScreenshots.splice(8);
  return screenshot;
});
ipcMain.handle('screenshot:list-recent', (event) => {
  assertTrustedAppSender(event);
  pruneRecentScreenshots();
  return recentScreenshots.map((item) => ({ ...item }));
});
ipcMain.handle('screenshot:delete-recent', (event, id: unknown) => {
  assertTrustedAppSender(event);
  if (typeof id === 'string') {
    const index = recentScreenshots.findIndex((item) => item.id === id);
    if (index >= 0) recentScreenshots.splice(index, 1);
  }
});
ipcMain.handle('platform:get-settings', (event) => {
  assertTrustedAppSender(event);
  return platformSettingsSnapshot();
});
ipcMain.handle('platform:get-system-access-status', (event) => {
  assertTrustedAppSender(event);
  return getSystemAccessStatus();
});
ipcMain.handle('platform:retry-session-screenshot', async (event) => {
  assertTrustedAppSender(event);
  const { conversationId, lastInteractionAt } = screenshotContext;
  if (!conversationId || Date.now() - lastInteractionAt > 60_000) {
    return { started: false, reason: '请先打开一个会话并进行一次交互，然后再试。' };
  }
  await captureSessionScreenshot();
  return { started: true };
});
ipcMain.handle('platform:request-system-access', async (event) => {
  assertTrustedAppSender(event);
  if (process.platform === 'darwin') {
    try { systemPreferences.isTrustedAccessibilityClient(true); } catch { /* OS permission APIs are version-specific */ }
    try { await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 16, height: 16 } }); } catch { /* A denied screen permission is reported below. */ }
  }
  return getSystemAccessStatus();
});
ipcMain.handle('platform:open-system-privacy-settings', async (event, section: unknown) => {
  assertTrustedAppSender(event);
  if (process.platform === 'darwin') await shell.openExternal(section === 'accessibility'
    ? 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'
    : 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture');
});
ipcMain.handle('platform:set-always-on-top', (event, enabled: unknown) => {
  assertTrustedAppSender(event);
  if (typeof enabled !== 'boolean') throw new Error('置顶设置必须是布尔值。');
  savePlatformPreferences({ ...platformPreferences, alwaysOnTop: enabled });
  if (windowRef && !windowRef.isDestroyed()) windowRef.setAlwaysOnTop(enabled);
  return platformSettingsSnapshot();
});
ipcMain.handle('platform:set-keep-awake', (event, enabled: unknown) => {
  assertTrustedAppSender(event);
  if (typeof enabled !== 'boolean') throw new Error('防休眠设置必须是布尔值。');
  keepAwakeEnabled = enabled;
  updateRuntimeState(runtimeState);
});
ipcMain.on('voice-hud:result', (event, value: unknown) => {
  if (typeof value !== 'string') return;
  const transcript = value.trim().slice(0, 12000);
  if (!transcript) return;
  const deliver = () => {
    if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('app:voice-hud-result', transcript);
  };
  if (!windowRef || windowRef.isDestroyed()) {
    // Keep the result until the user next opens Atlas; never raise the window
    // merely because a dictation completed in another app.
    pendingVoiceHudResults.push(transcript);
    return;
  }
  if (windowRef.webContents.isLoading()) windowRef.webContents.once('did-finish-load', deliver);
  else deliver();
});

ipcMain.on('runtime:set-state', (event, state: unknown) => {
  assertTrustedAppSender(event);
  if (state === 'running' || state === 'waiting' || state === 'idle') updateRuntimeState(state);
});
ipcMain.handle('task-hud:toggle', (event) => { assertTrustedAppSender(event); return toggleTaskHud(); });
ipcMain.on('browser:address-shortcut-target', (event, rawId: unknown) => {
  assertTrustedAppSender(event);
  if (browserAddressShortcutTarget && browserAddressShortcutListener) browserAddressShortcutTarget.removeListener('before-input-event', browserAddressShortcutListener);
  browserAddressShortcutTarget = null; browserAddressShortcutListener = null;
  if (typeof rawId !== 'number' || !Number.isInteger(rawId)) return;
  const guest = webContents.fromId(rawId);
  if (!guest || guest.isDestroyed()) return;
  browserAddressShortcutTarget = guest;
  browserAddressShortcutListener = (inputEvent, input) => {
    if (input.type !== 'keyDown' || !(input.control || input.meta) || input.key.toLowerCase() !== 'l') return;
    inputEvent.preventDefault();
    if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('browser:focus-address');
  };
  guest.on('before-input-event', browserAddressShortcutListener);
});
ipcMain.on('task-hud:update', (event, raw: unknown) => {
  assertTrustedAppSender(event);
  if (!raw || typeof raw !== 'object') return;
  const data = raw as Record<string, unknown>;
  if (data.state !== 'running' && data.state !== 'waiting' && data.state !== 'idle') return;
  taskHudData = { state: data.state, summary: typeof data.summary === 'string' ? data.summary.slice(0, 180) : '任务状态', conversationId: typeof data.conversationId === 'string' ? data.conversationId.slice(0, 128) : '' };
  if (taskHudWindow && !taskHudWindow.isDestroyed()) taskHudWindow.webContents.send('task-hud:data', taskHudData);
});
ipcMain.on('task-hud:click-through', (event, enabled: unknown) => {
  if (event.sender !== taskHudWindow?.webContents || event.senderFrame !== event.sender.mainFrame) return;
  taskHudWindow.setIgnoreMouseEvents(enabled === true, { forward: true });
});
ipcMain.on('task-hud:return', (event) => {
  if (event.sender !== taskHudWindow?.webContents || event.senderFrame !== event.sender.mainFrame) return;
  if (windowRef && !windowRef.isDestroyed()) { windowRef.show(); windowRef.focus(); windowRef.webContents.send('task-hud:return', taskHudData.conversationId); }
});
ipcMain.on('task-hud:hide', (event) => { if (event.sender === taskHudWindow?.webContents) taskHudWindow.hide(); });
ipcMain.on('task-hud:close', (event) => { if (event.sender === taskHudWindow?.webContents) taskHudWindow.close(); });
ipcMain.on('app:set-quit-activity', (event, summary: unknown) => {
  assertTrustedAppSender(event);
  if (!summary || typeof summary !== 'object') return;
  const value = summary as Record<string, unknown>;
  const count = (raw: unknown) => typeof raw === 'number' && Number.isFinite(raw) ? Math.max(0, Math.min(10000, Math.floor(raw))) : 0;
  quitActivitySummary = { runningTasks: count(value.runningTasks), scheduledTasks: count(value.scheduledTasks) };
});
ipcMain.handle('app:quit-request', async (event) => {
  assertTrustedAppSender(event);
  return requestExplicitQuit(BrowserWindow.fromWebContents(event.sender));
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
async function restartBackendNow(reason: string, safeMode = platformPreferences.safeModeOnNextStart): Promise<void> {
  savePlatformPreferences({ ...platformPreferences, safeModeOnNextStart: safeMode });
  await stopManagedBackend(reason);
  publishBackendLifecycle({ kind: 'shutdown-complete' });
  const pid = readRunningBackendPid();
  if (pid !== null) await terminateBackendPid(pid, reason);
  startBackend(true);
}

ipcMain.handle('backend:retry', (event) => {
  assertTrustedAppSender(event);
  void restartBackendNow('user_retry');
});
ipcMain.handle('backend:get-lifecycle', (event) => {
  assertTrustedAppSender(event);
  return lastBackendLifecycle;
});
ipcMain.handle('backend:restart', async (event, safeMode: unknown) => {
  assertTrustedAppSender(event);
  if (typeof safeMode !== 'boolean') throw new Error('重启模式参数无效。');
  await restartBackendNow(safeMode ? 'user_safe_mode_restart' : 'user_normal_restart', safeMode);
});
ipcMain.handle('backend:get-safe-mode', (event) => {
  assertTrustedAppSender(event);
  return backendSafeModeActive;
});
ipcMain.handle('backend:get-safe-mode-preference', (event) => {
  assertTrustedAppSender(event);
  return platformPreferences.safeModeOnNextStart;
});
ipcMain.handle('backend:set-safe-mode-preference', (event, enabled: unknown) => {
  assertTrustedAppSender(event);
  if (typeof enabled !== 'boolean') throw new Error('安全模式偏好必须是布尔值。');
  savePlatformPreferences({ ...platformPreferences, safeModeOnNextStart: enabled });
});
ipcMain.handle('data-root:switch', async (event, rawTarget: unknown) => {
  assertTrustedAppSender(event);
  if (typeof rawTarget !== 'string' || !path.isAbsolute(rawTarget)) throw new Error('数据目录必须是绝对路径。');
  const target = path.resolve(rawTarget);
  if (!existsSync(target)) throw new Error('目标数据目录不存在。');
  const oldRoot = currentDataRoot();
  if (target === oldRoot) throw new Error('目标目录已经是当前数据目录。');
  let verifiedTarget = false;
  try {
    const marker = JSON.parse(readFileSync(path.join(target, 'data', '.atlas-data-migration.json'), 'utf8')) as Record<string, unknown>;
    verifiedTarget = marker.verified === true && path.resolve(String(marker.target_root)) === target;
  } catch { /* may be a rollback to the previous, still-preserved source */ }
  let validRollback = false;
  try {
    const marker = JSON.parse(readFileSync(path.join(oldRoot, 'data', '.atlas-data-migration.json'), 'utf8')) as Record<string, unknown>;
    validRollback = marker.verified === true && typeof marker.source_root === 'string' && path.resolve(marker.source_root) === target;
  } catch { /* no prior verified migration */ }
  if (!verifiedTarget && !validRollback) throw new Error('目标目录没有已验证的迁移副本，也不是当前迁移的原始目录。');
  const preference = dataRootPreferencePath();
  mkdirSync(path.dirname(preference), { recursive: true });
  const temporary = `${preference}.tmp`;
  writeFileSync(temporary, `${JSON.stringify({ current_root: target, previous_root: oldRoot, updated_at: new Date().toISOString() }, null, 2)}\n`, 'utf8');
  renameSync(temporary, preference);
  process.env.ATLAS_DATA_DIR = target;
  const pid = readRunningBackendPid();
  await stopManagedBackend('data_root_switch');
  if (pid !== null) await terminateBackendPid(pid, 'data_root_switch');
  app.relaunch();
  app.exit(0);
  return { restarting: true };
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
ipcMain.handle('platform:set-screenshot-shortcut', (event, accelerator: unknown) => {
  assertTrustedAppSender(event);
  if (accelerator !== null && typeof accelerator !== 'string') throw new Error('截图快捷键格式无效。');
  return setScreenshotShortcut(accelerator as string | null);
});
ipcMain.handle('platform:set-voice-shortcut', (event, accelerator: unknown) => {
  assertTrustedAppSender(event);
  if (accelerator !== null && typeof accelerator !== 'string') throw new Error('语音快捷键格式无效。');
  return setVoiceShortcut(accelerator as string | null);
});
ipcMain.on('platform:set-screenshot-context', (event, conversationId: unknown, lastInteractionAt: unknown) => {
  assertTrustedAppSender(event);
  if (typeof conversationId !== 'string' || typeof lastInteractionAt !== 'number' || !Number.isFinite(lastInteractionAt)) return;
  screenshotContext = { conversationId: conversationId.slice(0, 128), lastInteractionAt };
});
ipcMain.handle('platform:open-workspace-in-editor', async (event, editor: unknown, workspacePath: unknown) => {
  assertTrustedAppSender(event);
  if (typeof editor !== 'string' || !Object.prototype.hasOwnProperty.call(IDE_COMMANDS, editor)) {
    throw new Error('不支持的编辑器。');
  }
  if (typeof workspacePath !== 'string') throw new Error('请选择一个有效的本地工作区目录。');
  await openWorkspaceInEditor(editor as PlatformEditorId, workspacePath);
});
ipcMain.handle('floating-composer:show', (event, context: unknown) => {
  assertTrustedAppSender(event);
  showFloatingComposer(context && typeof context === 'object' ? context as { selectedText?: string; conversationId?: string } : undefined);
});
ipcMain.handle('floating-composer:get-context', (event) => {
  if (event.sender !== floatingComposerWindow?.webContents || event.senderFrame !== event.sender.mainFrame) return { selectedText: '' };
  return floatingComposerContext;
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
ipcMain.on('floating-composer:return-draft', (event, payload: unknown) => {
  if (event.sender !== floatingComposerWindow?.webContents || event.senderFrame !== event.sender.mainFrame) return;
  if (!payload || typeof payload !== 'object') return;
  const draft = payload as { text?: unknown; conversationId?: unknown };
  if (typeof draft.text !== 'string' || !draft.text.trim() || draft.text.length > 20_000) return;
  const conversationId = typeof draft.conversationId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(draft.conversationId)
    ? draft.conversationId : '';
  if (windowRef && !windowRef.isDestroyed()) {
    windowRef.webContents.send('floating-composer:return-draft', { text: draft.text.trim(), conversationId });
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
ipcMain.handle('window:set-fullscreen', (event, enabled: unknown) => {
  assertTrustedAppSender(event);
  if (typeof enabled !== 'boolean') throw new Error('全屏状态必须为布尔值。');
  if (!windowRef || windowRef.isDestroyed()) return false;
  if (windowRef.isFullScreen() !== enabled) windowRef.setFullScreen(enabled);
  return windowRef.isFullScreen();
});
ipcMain.on('window:set-title', (event, value: unknown) => {
  assertTrustedAppSender(event);
  if (typeof value !== 'string' || !windowRef || windowRef.isDestroyed()) return;
  windowRef.setTitle(value.trim().slice(0, 180) || 'Atlas');
});
ipcMain.on('window:close', () => windowRef?.close());
// Source mode (running from a git checkout without the Vite dev server): updates are
// pulled and rebuilt by scripts/atlas-update.mjs instead of reinstalling a package.
const updateRoot = () => (!app.isPackaged && !process.env.VITE_DEV_SERVER_URL ? sourceRoot(app.getAppPath()) : null);
let releaseInstallerPath = '';
ipcMain.handle('update:check', () => checkSourceUpdate(updateRoot()));
ipcMain.handle('update:apply', async () => {
  const root = updateRoot();
  if (!root) return false;
  await stopManagedBackend();
  launchSourceUpdater(root);
  setImmediate(() => { explicitQuit = true; app.quit(); });
  return true;
});
ipcMain.handle('update:release-check', (_event, source: unknown) => checkReleaseUpdate(typeof source === 'string' ? source : '', app.getVersion(), app.getPath('userData')));
ipcMain.handle('update:release-download', async (_event, source: unknown, version: unknown) => {
  if (typeof source !== 'string' || typeof version !== 'string') throw new Error('更新源和版本号不能为空。');
  releaseInstallerPath = await downloadVerifiedInstaller(source, version, app.getPath('userData'), (percent) => {
    if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('update:release-progress', percent);
  });
  return releaseInstallerPath;
});
ipcMain.handle('update:release-install', async () => {
  if (!releaseInstallerPath) throw new Error('请先下载并验证更新包。');
  await stopManagedBackend();
  launchVerifiedInstaller(releaseInstallerPath, app.getPath('exe'), () => { explicitQuit = true; app.quit(); }, (error) => console.error(`Release installer failed to start: ${error.message}`));
  return true;
});
ipcMain.handle('update:release-skip', (_event, version: unknown) => {
  if (typeof version !== 'string' || !/^v?\d+\.\d+\.\d+/.test(version)) throw new Error('版本号无效。');
  setReleasePreference(app.getPath('userData'), { skipped: version });
});
ipcMain.handle('update:release-snooze', () => setReleasePreference(app.getPath('userData'), { remindAfter: Date.now() + 24 * 60 * 60 * 1000 }));
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
const savedScreenRecordings = new Set<string>();
ipcMain.handle('diagnostics:heap-snapshot', async (event) => {
  assertTrustedAppSender(event);
  const owner = BrowserWindow.fromWebContents(event.sender);
  const defaultPath = path.join(app.getPath('downloads'), `atlas-heap-${new Date().toISOString().replace(/[:.]/g, '-')}.heapsnapshot`);
  const options = { title: '导出 JavaScript Heap Snapshot', defaultPath, filters: [{ name: 'Heap Snapshot', extensions: ['heapsnapshot'] }] };
  const result = owner ? await dialog.showSaveDialog(owner, options) : await dialog.showSaveDialog(options);
  if (result.canceled || !result.filePath) return null;
  const contents = event.sender;
  if (contents.isDestroyed()) throw new Error('Atlas 窗口已关闭。');
  await contents.takeHeapSnapshot(result.filePath);
  return result.filePath;
});
ipcMain.handle('diagnostics:bug-bundle-save', async (event, payload: unknown, fileName: unknown) => {
  assertTrustedAppSender(event);
  if (typeof payload !== 'string' || Buffer.byteLength(payload, 'utf8') > 1024 * 1024) throw new Error('缺陷包内容无效或超过 1 MiB。');
  const parsed: unknown = JSON.parse(payload);
  if (!parsed || typeof parsed !== 'object' || (parsed as Record<string, unknown>).kind !== 'atlas-local-bug-bundle') throw new Error('缺陷包格式无效。');
  const requestedName = typeof fileName === 'string' ? fileName : 'atlas-bug-bundle.json';
  const safeName = path.basename(requestedName).replace(/[^\p{L}\p{N}._-]+/gu, '-').replace(/\.json$/i, '') + '.json';
  const options = {
    title: '保存脱敏 Bug Bundle',
    defaultPath: path.join(app.getPath('downloads'), safeName),
    filters: [{ name: 'JSON 文件', extensions: ['json'] }],
  };
  const owner = BrowserWindow.fromWebContents(event.sender);
  const result = owner ? await dialog.showSaveDialog(owner, options) : await dialog.showSaveDialog(options);
  if (result.canceled || !result.filePath) return null;
  writeFileSync(result.filePath, payload.endsWith('\n') ? payload : `${payload}\n`, { encoding: 'utf8', flag: 'w' });
  return path.resolve(result.filePath);
});
ipcMain.handle('diagnostics:trace-start', async (event) => {
  assertTrustedAppSender(event);
  if (performanceTraceActive) throw new Error('性能追踪已经在运行。');
  await contentTracing.startRecording({
    recording_mode: 'record-continuously',
    included_categories: ['-*', 'v8.execute', 'blink.user_timing', 'disabled-by-default-v8.cpu_profiler', 'disabled-by-default-devtools.timeline'],
  });
  performanceTraceActive = true;
});
ipcMain.handle('diagnostics:trace-stop', async (event) => {
  assertTrustedAppSender(event);
  if (!performanceTraceActive) throw new Error('当前没有运行中的性能追踪。');
  const temporaryDirectory = mkdtempSync(path.join(app.getPath('temp'), 'atlas-trace-'));
  const temporaryPath = path.join(temporaryDirectory, 'trace.json');
  try {
    const owner = BrowserWindow.fromWebContents(event.sender);
    const defaultPath = path.join(app.getPath('downloads'), `atlas-perf-${new Date().toISOString().replace(/[:.]/g, '-')}.json`);
    const options = { title: '保存性能追踪', defaultPath, filters: [{ name: 'Chrome Trace', extensions: ['json'] }] };
    const result = owner ? await dialog.showSaveDialog(owner, options) : await dialog.showSaveDialog(options);
    await contentTracing.stopRecording(temporaryPath);
    performanceTraceActive = false;
    if (result.canceled || !result.filePath) return null;
    const { copyFileSync } = await import('node:fs');
    copyFileSync(temporaryPath, result.filePath);
    return result.filePath;
  } finally {
    if (performanceTraceActive) {
      try { await contentTracing.stopRecording(temporaryPath); } catch { /* best-effort trace cleanup */ }
      performanceTraceActive = false;
    }
    rmSync(temporaryDirectory, { recursive: true, force: true });
  }
});
ipcMain.handle('screen-recording:save', async (event, dataBase64: unknown, fileName: unknown) => {
  if (event.sender !== windowRef?.webContents || event.senderFrame !== event.sender.mainFrame || typeof dataBase64 !== 'string' || typeof fileName !== 'string') throw new Error('屏幕录制只能从 Atlas 主窗口保存');
  if (dataBase64.length > 14 * 1024 * 1024 || !/^[A-Za-z0-9+/]*={0,2}$/.test(dataBase64)) throw new Error('录制视频数据格式无效或超过 10 MiB');
  const bytes = Buffer.from(dataBase64, 'base64');
  if (!bytes.length || bytes.length > 10 * 1024 * 1024) throw new Error('录制视频不得超过 10 MiB');
  const folder = path.join(app.getPath('videos'), 'Atlas'); mkdirSync(folder, { recursive: true });
  const safeName = path.basename(fileName).replace(/[^\p{L}\p{N}._-]+/gu, '-').replace(/\.webm$/i, '') + '.webm';
  const owner = BrowserWindow.fromWebContents(event.sender);
  const result = owner
    ? await dialog.showSaveDialog(owner, { title: '保存屏幕录制', defaultPath: path.join(folder, safeName), filters: [{ name: 'WebM 视频', extensions: ['webm'] }] })
    : await dialog.showSaveDialog({ title: '保存屏幕录制', defaultPath: path.join(folder, safeName), filters: [{ name: 'WebM 视频', extensions: ['webm'] }] });
  if (result.canceled || !result.filePath) return null;
  writeFileSync(result.filePath, bytes, { flag: 'w' });
  const savedPath = path.resolve(result.filePath); savedScreenRecordings.add(savedPath);
  return savedPath;
});
ipcMain.handle('screen-recording:delete', (event, target: unknown) => {
  if (event.sender !== windowRef?.webContents || event.senderFrame !== event.sender.mainFrame || typeof target !== 'string') return false;
  const savedPath = path.resolve(target);
  if (!savedScreenRecordings.has(savedPath)) return false;
  rmSync(savedPath, { force: true }); savedScreenRecordings.delete(savedPath); return true;
});
ipcMain.handle('shell:open-path', async (event, target?: unknown) => {
  if (event.sender !== windowRef?.webContents || typeof target !== 'string' || !path.isAbsolute(target)) return 'invalid path';
  if (RUNNABLE.test(target)) { shell.showItemInFolder(target); return 'revealed'; }
  const error = await shell.openPath(target);
  return error || 'opened';
});
ipcMain.handle('shell:open-external', async (event, target?: unknown) => {
  if (event.sender !== windowRef?.webContents || event.senderFrame !== event.sender.mainFrame || typeof target !== 'string') return false;
  let dashboardUrl = false;
  try {
    const parsed = new URL(target);
    dashboardUrl = parsed.protocol === 'http:' && parsed.hostname === '127.0.0.1'
      && /^\d+$/.test(parsed.port) && parsed.pathname === '/dashboard'
      && /^[A-Za-z0-9_-]{32,256}$/.test(parsed.hash.slice(1));
  } catch { /* other explicitly supported schemes are checked below */ }
  if (!dashboardUrl && !['chrome://extensions', 'edge://extensions', 'ms-settings:network-proxy'].includes(target)
      && !/^https:\/\/[a-z0-9.-]+(?:\/[^\s]*)?$/i.test(target)) return false;
  await shell.openExternal(target);
  return true;
});

ipcMain.handle('speech:synthesize', (event, rawText: unknown, rawVoice: unknown, rawRate: unknown) => {
  assertTrustedAppSender(event);
  if (process.platform !== 'win32') throw new Error('可路由的本机语音输出目前只支持 Windows System.Speech。');
  if (typeof rawText !== 'string' || !rawText.trim() || rawText.length > 6000
      || typeof rawVoice !== 'string' || rawVoice.length > 256
      || typeof rawRate !== 'number' || !Number.isFinite(rawRate) || rawRate < 0.5 || rawRate > 2) {
    throw new Error('语音文本、音色或语速参数无效。');
  }
  const temporaryWave = path.join(app.getPath('temp'), `atlas-speech-${randomUUID()}.wav`);
  const payload = Buffer.from(JSON.stringify({ text: rawText, voice: rawVoice, rate: rawRate, outputPath: temporaryWave }), 'utf8').toString('base64');
  const script = [
    "$ErrorActionPreference = 'Stop'",
    'Add-Type -AssemblyName System.Speech',
    `$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${payload}')) | ConvertFrom-Json`,
    "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer",
    'try {',
    '  if ($data.voice) { if (-not ($synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Name -eq $data.voice })) { throw \'Selected system voice is unavailable\' }; $synth.SelectVoice($data.voice) }',
    '  $synth.Rate = [Math]::Max(-10, [Math]::Min(10, [int][Math]::Round(($data.rate - 1) * 10)))',
    '  $synth.SetOutputToWaveFile([string]$data.outputPath)',
    '  $synth.Speak([string]$data.text)',
    '  [Convert]::ToBase64String([IO.File]::ReadAllBytes([string]$data.outputPath))',
    '} finally { $synth.Dispose(); Remove-Item -LiteralPath ([string]$data.outputPath) -Force -ErrorAction SilentlyContinue }',
  ].join('\n');
  const encoded = Buffer.from(script, 'utf16le').toString('base64');
  const result = spawnSync('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], {
    windowsHide: true, encoding: 'utf8', timeout: 30_000, maxBuffer: 16 * 1024 * 1024,
  });
  if (result.error || result.status !== 0 || !result.stdout?.trim()) {
    rmSync(temporaryWave, { force: true });
    throw new Error(`Windows 语音合成失败：${result.error?.message ?? (result.stderr || `PowerShell exit ${result.status}`).trim().slice(-500)}`);
  }
  return result.stdout.trim();
});

ipcMain.handle('editor:open-message', async (event, rawText?: unknown) => {
  if (event.sender !== windowRef?.webContents || event.senderFrame !== event.sender.mainFrame) {
    throw new Error('External editor can only be opened from the Atlas main window');
  }
  const tempDir = mkdtempSync(path.join(app.getPath('temp'), 'atlas-message-'));
  const filePath = path.join(tempDir, 'message.md');
  writeFileSync(filePath, typeof rawText === 'string' ? rawText : '', 'utf8');
  const configured = process.env.VISUAL || process.env.EDITOR || '';
  const parts = configured.match(/(?:"[^"]*"|'[^']*'|[^\s]+)/g)?.map((item) => item.replace(/^(?:"(.*)"|'(.*)')$/, (_match, doubleQuoted, singleQuoted) => doubleQuoted ?? singleQuoted)) ?? [];
  const command = parts[0] || (process.platform === 'win32' ? 'notepad.exe' : process.platform === 'darwin' ? 'open' : 'xdg-open');
  const args = [...parts.slice(1), ...(command === 'open' ? ['-W', '-t', filePath] : [filePath])];
  try {
    await new Promise<void>((resolve, reject) => {
      const child = spawn(command, args, { stdio: 'ignore', windowsHide: true });
      child.once('error', reject);
      child.once('exit', (code) => code === 0 || code === null ? resolve() : reject(new Error(`Editor exited with code ${code}`)));
    });
    return readFileSync(filePath, 'utf8');
  } finally { rmSync(tempDir, { recursive: true, force: true }); }
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
  await injectBackendPort();
  applySavedDataRoot();
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
  createApplicationMenu();
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
  if (platformPreferences.safeModeOnNextStart) void restartBackendNow('safe_mode_preference_start', true);
  else startBackend();
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
    publishBackendLifecycle({ kind: 'shutdown-complete' });
    shutdownComplete = true;
    app.quit();
  });
});

app.on('window-all-closed', () => { /* Atlas stays available from the tray. */ });
