import { app, BrowserWindow, dialog, ipcMain, session, shell } from 'electron';
import { randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ensureBackendRunning, stopManagedBackend } from './backendProcess.js';

const here = path.dirname(fileURLToPath(import.meta.url));
let windowRef: BrowserWindow | null = null;
process.env.ATLAS_SKILL_CENTER_TOKEN ??= randomBytes(32).toString('base64url');
// Proves to the backend that a request comes from this app rather than some web page.
// Only the main process ever sees it: it is attached below, outside the renderer.
process.env.ATLAS_API_TOKEN ??= randomBytes(32).toString('base64url');

/** Session for pages shown in the browser panel. Separate from the app's, so they never get the backend token. */
export const BROWSER_PARTITION = 'persist:atlas-browser';

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
    callback({ requestHeaders: { ...details.requestHeaders, 'X-Atlas-Api-Token': process.env.ATLAS_API_TOKEN ?? '' } });
  });
}

function createWindow() {
  windowRef = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1050,
    minHeight: 680,
    backgroundColor: '#faf9f6',
    title: 'Atlas · Agent Workspace',
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

  windowRef.on('maximize', () => windowRef?.webContents.send('window:maximize-change', true));
  windowRef.on('unmaximize', () => windowRef?.webContents.send('window:maximize-change', false));
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  // The app window carries the preload API and its requests get the backend token, so it must
  // never become a window onto someone else's page: links open in the system browser instead,
  // and navigation away from the app is refused.
  const appUrl = devUrl ? new URL(devUrl).origin : pathToFileURL(path.join(here, '../../dist/index.html')).href;
  const isAppUrl = (target: string) => devUrl ? target.startsWith(appUrl) : target.split('#')[0] === appUrl;
  windowRef.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  windowRef.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return;
    event.preventDefault();
    if (/^https?:/i.test(url)) void shell.openExternal(url);
  });
  if (devUrl) void windowRef.loadURL(devUrl);
  else void windowRef.loadFile(path.join(here, '../../dist/index.html'));
  windowRef.on('closed', () => { windowRef = null; });
}

ipcMain.on('window:minimize', () => windowRef?.minimize());
ipcMain.on('window:maximize', () => {
  if (!windowRef) return;
  if (windowRef.isMaximized()) windowRef.unmaximize();
  else windowRef.maximize();
});
ipcMain.on('window:close', () => windowRef?.close());
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
  try {
    await ensureBackendRunning();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    dialog.showErrorBox('Atlas backend startup failed', `Atlas could not start its backend.\n\n${message}`);
    app.quit();
    return;
  }
  attachBackendToken();
  lockDownWebviews();
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

let shutdownStarted = false;
let shutdownComplete = false;
app.on('before-quit', (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  if (shutdownStarted) return;
  shutdownStarted = true;
  void stopManagedBackend().finally(() => {
    shutdownComplete = true;
    app.quit();
  });
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
