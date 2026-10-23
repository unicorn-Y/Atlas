import { contextBridge, ipcRenderer } from 'electron';
import type { AtlasDeepLink, AtlasDesktopApi, BackendStartupProgress, PlatformEditorId } from '../shared/ipc.js';
import { BACKEND_STARTUP_CHANNEL } from '../shared/ipc.js';

const desktopApi: AtlasDesktopApi = {
  platform: process.platform,
  apiBaseUrl: process.env.ATLAS_API_BASE_URL ?? `http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}`,
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close: () => ipcRenderer.send('window:close'),
  retryBackend: () => ipcRenderer.invoke('backend:retry') as Promise<void>,
  openBackendLog: () => ipcRenderer.invoke('backend:open-log') as Promise<void>,
  setTheme: (theme) => ipcRenderer.send('window:theme', theme),
  checkForUpdate: () => ipcRenderer.invoke('update:check'),
  applyUpdate: () => ipcRenderer.invoke('update:apply') as Promise<boolean>,
  getSkillCenterToken: () => ipcRenderer.invoke('skill-center:token') as Promise<string | undefined>,
  selectDirectory: (defaultPath) => ipcRenderer.invoke('dialog:open-directory', defaultPath) as Promise<string | null>,
  openPath: (target) => ipcRenderer.invoke('shell:open-path', target) as Promise<string>,
  getPlatformSettings: () => ipcRenderer.invoke('platform:get-settings'),
  setAlwaysOnTop: (enabled) => ipcRenderer.invoke('platform:set-always-on-top', enabled),
  setOpenAtLogin: (enabled) => ipcRenderer.invoke('platform:set-open-at-login', enabled),
  setGlobalShortcut: (accelerator) => ipcRenderer.invoke('platform:set-global-shortcut', accelerator),
  openWorkspaceInEditor: (editor: PlatformEditorId, workspacePath: string) =>
    ipcRenderer.invoke('platform:open-workspace-in-editor', editor, workspacePath),
  showFloatingComposer: () => ipcRenderer.invoke('floating-composer:show'),
  openConversationWindow: (conversationId: string) => ipcRenderer.invoke('conversation:open-window', conversationId),
  hideFloatingComposer: () => ipcRenderer.send('floating-composer:hide'),
  submitFloatingComposer: (text: string) => ipcRenderer.send('floating-composer:submit', text),
  onFloatingComposerSubmit: (callback: (text: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, text: string) => callback(text);
    ipcRenderer.on('floating-composer:deliver', listener);
    return () => ipcRenderer.removeListener('floating-composer:deliver', listener);
  },
  openFileInEditor: (editor: PlatformEditorId, workspacePath: string, filePath: string) =>
    ipcRenderer.invoke('platform:open-file-in-editor', editor, workspacePath, filePath),
  onDeepLink: (callback: (route: AtlasDeepLink) => void) => {
    let active = true;
    const seen = new Set<string>();
    const deliver = (route: AtlasDeepLink) => {
      if (!active || seen.has(route.id)) return;
      seen.add(route.id);
      callback(route);
    };
    const listener = (_event: Electron.IpcRendererEvent, route: AtlasDeepLink) => deliver(route);
    ipcRenderer.on('app:deep-link', listener);
    void ipcRenderer.invoke('deep-link:subscribe').then((queued: AtlasDeepLink[]) => queued.forEach(deliver)).catch(() => undefined);
    return () => {
      active = false;
      ipcRenderer.removeListener('app:deep-link', listener);
      ipcRenderer.send('deep-link:unsubscribe');
    };
  },
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
