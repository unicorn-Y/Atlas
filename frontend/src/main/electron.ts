import { app, BrowserWindow, dialog, ipcMain } from 'electron';
import { randomBytes } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ensureBackendRunning, stopManagedBackend } from './backendProcess.js';

const here = path.dirname(fileURLToPath(import.meta.url));
let windowRef: BrowserWindow | null = null;
process.env.ATLAS_SKILL_CENTER_TOKEN ??= randomBytes(32).toString('base64url');

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
      preload: path.join(here, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  windowRef.on('maximize', () => windowRef?.webContents.send('window:maximize-change', true));
  windowRef.on('unmaximize', () => windowRef?.webContents.send('window:maximize-change', false));
  const devUrl = process.env.VITE_DEV_SERVER_URL;
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
  }
  try {
    await ensureBackendRunning();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    dialog.showErrorBox('Atlas backend startup failed', `Atlas could not start its backend.\n\n${message}`);
    app.quit();
    return;
  }
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
