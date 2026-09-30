import { contextBridge, ipcRenderer } from 'electron';
import type { AtlasDesktopApi } from '../shared/ipc.js';

const desktopApi: AtlasDesktopApi = {
  platform: process.platform,
  apiBaseUrl: process.env.ATLAS_API_BASE_URL ?? `http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}`,
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close: () => ipcRenderer.send('window:close'),
  getSkillCenterToken: () => ipcRenderer.invoke('skill-center:token') as Promise<string | undefined>,
  selectDirectory: (defaultPath) => ipcRenderer.invoke('dialog:open-directory', defaultPath) as Promise<string | null>,
  onMaximizeChange: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, maximized: boolean) => callback(maximized);
    ipcRenderer.on('window:maximize-change', listener);
    return () => ipcRenderer.removeListener('window:maximize-change', listener);
  },
};

contextBridge.exposeInMainWorld('atlasDesktop', desktopApi);
