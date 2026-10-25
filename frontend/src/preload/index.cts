import { contextBridge, ipcRenderer } from 'electron';
import type { AtlasDeepLink, AtlasDesktopApi, BackendStartupProgress, PlatformEditorId, ReleaseUpdateStatus } from '../shared/ipc.js';
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
  checkReleaseUpdate: (source: string) => ipcRenderer.invoke('update:release-check', source) as Promise<ReleaseUpdateStatus>,
  downloadReleaseUpdate: (source: string, version: string) => ipcRenderer.invoke('update:release-download', source, version) as Promise<string>,
  installReleaseUpdate: () => ipcRenderer.invoke('update:release-install') as Promise<boolean>,
  skipReleaseVersion: (version: string) => ipcRenderer.invoke('update:release-skip', version) as Promise<void>,
  remindReleaseLater: () => ipcRenderer.invoke('update:release-snooze') as Promise<void>,
  onReleaseDownloadProgress: (callback) => { const listener = (_event: Electron.IpcRendererEvent, percent: number) => callback(percent); ipcRenderer.on('update:release-progress', listener); return () => ipcRenderer.removeListener('update:release-progress', listener); },
  getSkillCenterToken: () => ipcRenderer.invoke('skill-center:token') as Promise<string | undefined>,
  selectDirectory: (defaultPath) => ipcRenderer.invoke('dialog:open-directory', defaultPath) as Promise<string | null>,
  openPath: (target) => ipcRenderer.invoke('shell:open-path', target) as Promise<string>,
  openExternal: (target) => ipcRenderer.invoke('shell:open-external', target) as Promise<boolean>,
  synthesizeSpeech: (text, voice, rate) => ipcRenderer.invoke('speech:synthesize', text, voice, rate) as Promise<string>,
  openMessageEditor: (text) => ipcRenderer.invoke('editor:open-message', text) as Promise<string | null>,
  saveScreenRecording: (dataBase64, fileName) => ipcRenderer.invoke('screen-recording:save', dataBase64, fileName) as Promise<string | null>,
  deleteScreenRecording: (filePath) => ipcRenderer.invoke('screen-recording:delete', filePath) as Promise<boolean>,
  getPlatformSettings: () => ipcRenderer.invoke('platform:get-settings'),
  setAlwaysOnTop: (enabled) => ipcRenderer.invoke('platform:set-always-on-top', enabled),
  setOpenAtLogin: (enabled) => ipcRenderer.invoke('platform:set-open-at-login', enabled),
  setGlobalShortcut: (accelerator) => ipcRenderer.invoke('platform:set-global-shortcut', accelerator),
  setScreenshotShortcut: (accelerator) => ipcRenderer.invoke('platform:set-screenshot-shortcut', accelerator),
  setVoiceShortcut: (accelerator) => ipcRenderer.invoke('platform:set-voice-shortcut', accelerator),
  onVoiceHotkey: (callback) => { const listener = () => callback(); ipcRenderer.on('app:voice-hotkey', listener); return () => ipcRenderer.removeListener('app:voice-hotkey', listener); },
  onVoiceHudStart: (callback) => { const listener = () => callback(); ipcRenderer.on('voice-hud:start', listener); return () => ipcRenderer.removeListener('voice-hud:start', listener); },
  onVoiceHudStop: (callback) => { const listener = () => callback(); ipcRenderer.on('voice-hud:stop', listener); return () => ipcRenderer.removeListener('voice-hud:stop', listener); },
  switchDataRoot: (target) => ipcRenderer.invoke('data-root:switch', target) as Promise<{ restarting: boolean }>,
  setScreenshotContext: (conversationId, lastInteractionAt) => ipcRenderer.send('platform:set-screenshot-context', conversationId, lastInteractionAt),
  onSessionScreenshot: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, dataUrl: string, conversationId: string) => callback(dataUrl, conversationId);
    ipcRenderer.on('app:session-screenshot', listener);
    return () => ipcRenderer.removeListener('app:session-screenshot', listener);
  },
  onSessionScreenshotError: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, message: string) => callback(message);
    ipcRenderer.on('app:session-screenshot-error', listener);
    return () => ipcRenderer.removeListener('app:session-screenshot-error', listener);
  },
  retrySessionScreenshot: () => ipcRenderer.invoke('platform:retry-session-screenshot'),
  getSystemAccessStatus: () => ipcRenderer.invoke('platform:get-system-access-status'),
  requestSystemAccess: () => ipcRenderer.invoke('platform:request-system-access'),
  openSystemPrivacySettings: () => ipcRenderer.invoke('platform:open-system-privacy-settings'),
  setKeepAwake: (enabled) => ipcRenderer.invoke('platform:set-keep-awake', enabled) as Promise<void>,
  setRuntimeState: (state) => ipcRenderer.send('runtime:set-state', state),
  openWorkspaceInEditor: (editor: PlatformEditorId, workspacePath: string) =>
    ipcRenderer.invoke('platform:open-workspace-in-editor', editor, workspacePath),
  showFloatingComposer: () => ipcRenderer.invoke('floating-composer:show'),
  openConversationWindow: (conversationId: string) => ipcRenderer.invoke('conversation:open-window', conversationId),
  openNewWindow: () => ipcRenderer.invoke('conversation:open-window'),
  openNewSessionWindow: () => ipcRenderer.invoke('conversation:open-window', undefined, true),
  listCaptureWindows: () => ipcRenderer.invoke('screenshot:list-windows'),
  captureWindow: (sourceId: string, conversationId: string) => ipcRenderer.invoke('screenshot:capture-window', sourceId, conversationId),
  listRecentScreenshots: () => ipcRenderer.invoke('screenshot:list-recent'),
  deleteRecentScreenshot: (id: string) => ipcRenderer.invoke('screenshot:delete-recent', id),
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
  onBrowserFind: (callback) => {
    const listener = () => callback();
    ipcRenderer.on('browser:find', listener);
    return () => ipcRenderer.removeListener('browser:find', listener);
  },
};

contextBridge.exposeInMainWorld('atlasDesktop', desktopApi);
