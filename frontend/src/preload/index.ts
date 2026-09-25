import { contextBridge, ipcRenderer } from 'electron';
import type { AtlasDesktopApi } from '../shared/ipc.js';

const desktopApi: AtlasDesktopApi = {
  platform: process.platform,
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close: () => ipcRenderer.send('window:close'),
  onMaximizeChange: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, maximized: boolean) => callback(maximized);
    ipcRenderer.on('window:maximize-change', listener);
    return () => ipcRenderer.removeListener('window:maximize-change', listener);
  },
};

contextBridge.exposeInMainWorld('atlasDesktop', desktopApi);
