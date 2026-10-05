import { contextBridge, ipcRenderer } from 'electron';
import type { AtlasDesktopApi, BackendStartupProgress } from '../shared/ipc.js';
import { BACKEND_STARTUP_CHANNEL } from '../shared/ipc.js';

const desktopApi: AtlasDesktopApi = {
  platform: process.platform,
  apiBaseUrl: process.env.ATLAS_API_BASE_URL ?? `http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}`,
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close: () => ipcRenderer.send('window:close'),
  setTheme: (theme) => ipcRenderer.send('window:theme', theme),
  checkForUpdate: () => ipcRenderer.invoke('update:check'),
  applyUpdate: () => ipcRenderer.invoke('update:apply') as Promise<boolean>,
  getSkillCenterToken: () => ipcRenderer.invoke('skill-center:token') as Promise<string | undefined>,
  selectDirectory: (defaultPath) => ipcRenderer.invoke('dialog:open-directory', defaultPath) as Promise<string | null>,
  openPath: (target) => ipcRenderer.invoke('shell:open-path', target) as Promise<string>,
  onMaximizeChange: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, maximized: boolean) => callback(maximized);
    ipcRenderer.on('window:maximize-change', listener);
    return () => ipcRenderer.removeListener('window:maximize-change', listener);
  },
  onBackendStartupProgress: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, progress: BackendStartupProgress) => callback(progress);
    ipcRenderer.on(BACKEND_STARTUP_CHANNEL, listener);
    return () => ipcRenderer.removeListener(BACKEND_STARTUP_CHANNEL, listener);
  },
};

contextBridge.exposeInMainWorld('atlasDesktop', desktopApi);
