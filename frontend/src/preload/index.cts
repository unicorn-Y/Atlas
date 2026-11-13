import { contextBridge, ipcRenderer } from 'electron';
import type { AtlasDeepLink, AtlasDesktopApi, BackendLifecycleEvent, BackendStartupProgress, PlatformEditorId, ReleaseUpdateStatus } from '../shared/ipc.js';

const BACKEND_STARTUP_CHANNEL = 'backend:startup-progress';

const desktopApi: AtlasDesktopApi = {
  platform: process.platform,
  apiBaseUrl: process.env.ATLAS_API_BASE_URL ?? `http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}`,
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  setWindowFullScreen: (enabled: boolean) => ipcRenderer.invoke('window:set-fullscreen', enabled) as Promise<boolean>,
  setWindowTitle: (title: string) => ipcRenderer.send('window:set-title', title),
  onWindowFullScreenChange: (callback: (fullScreen: boolean) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, fullScreen: boolean) => callback(fullScreen);
    ipcRenderer.on('window:fullscreen-change', listener);
    return () => ipcRenderer.removeListener('window:fullscreen-change', listener);
  },
  close: () => ipcRenderer.send('window:close'),
  requestQuit: () => ipcRenderer.invoke('app:quit-request') as Promise<boolean>,
  setQuitActivity: (summary: { runningTasks: number; scheduledTasks: number }) => ipcRenderer.send('app:set-quit-activity', summary),
  saveBugBundle: (payload: string, fileName?: string) => ipcRenderer.invoke('diagnostics:bug-bundle-save', payload, fileName) as Promise<string | null>,
  retryBackend: () => ipcRenderer.invoke('backend:retry') as Promise<void>,
  restartBackend: (safeMode: boolean) => ipcRenderer.invoke('backend:restart', safeMode) as Promise<void>,
  getSafeMode: () => ipcRenderer.invoke('backend:get-safe-mode') as Promise<boolean>,
  getSafeModePreference: () => ipcRenderer.invoke('backend:get-safe-mode-preference') as Promise<boolean>,
  setSafeModePreference: (enabled: boolean) => ipcRenderer.invoke('backend:set-safe-mode-preference', enabled) as Promise<void>,
  openBackendLog: () => ipcRenderer.invoke('backend:open-log') as Promise<void>,
  captureHeapSnapshot: () => ipcRenderer.invoke('diagnostics:heap-snapshot') as Promise<string | null>,
  startPerformanceTrace: () => ipcRenderer.invoke('diagnostics:trace-start') as Promise<void>,
  stopPerformanceTrace: () => ipcRenderer.invoke('diagnostics:trace-stop') as Promise<string | null>,
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
  onVoiceHotkeyStop: (callback) => { const listener = () => callback(); ipcRenderer.on('app:voice-hotkey-stop', listener); return () => ipcRenderer.removeListener('app:voice-hotkey-stop', listener); },
  acknowledgeVoiceHotkeyStop: () => ipcRenderer.send('app:voice-hotkey-stopped'),
  onVoiceHudResult: (callback) => { const listener = (_event: Electron.IpcRendererEvent, transcript: string) => callback(transcript); ipcRenderer.on('app:voice-hud-result', listener); return () => ipcRenderer.removeListener('app:voice-hud-result', listener); },
  submitVoiceHudResult: (transcript) => ipcRenderer.send('voice-hud:result', transcript),
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
  toggleTaskHud: () => ipcRenderer.invoke('task-hud:toggle') as Promise<boolean>,
  updateTaskHud: (data) => ipcRenderer.send('task-hud:update', data),
  setTaskHudClickThrough: (enabled) => ipcRenderer.send('task-hud:click-through', enabled),
  onTaskHudData: (callback) => { const listener = (_event: Electron.IpcRendererEvent, data: { state: 'running' | 'waiting' | 'idle'; summary: string }) => callback(data); ipcRenderer.on('task-hud:data', listener); return () => ipcRenderer.removeListener('task-hud:data', listener); },
  onTaskHudClickThroughState: (callback) => { const listener = (_event: Electron.IpcRendererEvent, enabled: boolean) => callback(enabled); ipcRenderer.on('task-hud:click-through-state', listener); return () => ipcRenderer.removeListener('task-hud:click-through-state', listener); },
  onTaskHudReturn: (callback) => { const listener = (_event: Electron.IpcRendererEvent, conversationId: string) => callback(conversationId); ipcRenderer.on('task-hud:return', listener); return () => ipcRenderer.removeListener('task-hud:return', listener); },
  taskHudReturn: () => ipcRenderer.send('task-hud:return'),
  hideTaskHud: () => ipcRenderer.send('task-hud:hide'),
  closeTaskHud: () => ipcRenderer.send('task-hud:close'),
  togglePetOverlay: () => ipcRenderer.invoke('pet-overlay:toggle') as Promise<boolean>,
  onPetOverlayStateChange: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, state: 'running' | 'waiting' | 'idle') => callback(state);
    ipcRenderer.on('pet-overlay:state', listener);
    return () => ipcRenderer.removeListener('pet-overlay:state', listener);
  },
  openWorkspaceInEditor: (editor: PlatformEditorId, workspacePath: string) =>
    ipcRenderer.invoke('platform:open-workspace-in-editor', editor, workspacePath),
  showFloatingComposer: (context) => ipcRenderer.invoke('floating-composer:show', context),
  openConversationWindow: (conversationId: string) => ipcRenderer.invoke('conversation:open-window', conversationId),
  focusApp: () => ipcRenderer.invoke('app:focus-window'),
  openSideChatWindow: (conversationId: string, initialQuestion?: string) => ipcRenderer.invoke('side-chat:open-window', conversationId, initialQuestion),
  openNewWindow: () => ipcRenderer.invoke('conversation:open-window'),
  openNewSessionWindow: () => ipcRenderer.invoke('conversation:open-window', undefined, true),
  listCaptureWindows: () => ipcRenderer.invoke('screenshot:list-windows'),
  captureWindow: (sourceId: string, conversationId: string) => ipcRenderer.invoke('screenshot:capture-window', sourceId, conversationId),
  listRecentScreenshots: () => ipcRenderer.invoke('screenshot:list-recent'),
  deleteRecentScreenshot: (id: string) => ipcRenderer.invoke('screenshot:delete-recent', id),
  hideFloatingComposer: () => ipcRenderer.send('floating-composer:hide'),
  submitFloatingComposer: (text: string) => ipcRenderer.send('floating-composer:submit', text),
  returnFloatingDraft: (text: string, conversationId?: string) => ipcRenderer.send('floating-composer:return-draft', { text, conversationId }),
  onFloatingDraft: (callback: (draft: { text: string; conversationId?: string }) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, draft: { text: string; conversationId?: string }) => callback(draft);
    ipcRenderer.on('floating-composer:return-draft', listener);
    return () => ipcRenderer.removeListener('floating-composer:return-draft', listener);
  },
  onFloatingComposerContext: (callback: (context: { selectedText: string; conversationId?: string }) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, context: { selectedText: string; conversationId?: string }) => callback(context);
    ipcRenderer.on('floating-composer:context', listener);
    return () => ipcRenderer.removeListener('floating-composer:context', listener);
  },
  getFloatingComposerContext: () => ipcRenderer.invoke('floating-composer:get-context') as Promise<{ selectedText: string; conversationId?: string }>,
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
  onBackendLifecycleEvent: (callback) => {
    let latestSequence = 0;
    const deliver = (value: BackendLifecycleEvent | null) => {
      if (!value || value.sequence <= latestSequence) return;
      latestSequence = value.sequence;
      callback(value);
    };
    const listener = (_event: Electron.IpcRendererEvent, value: BackendLifecycleEvent) => deliver(value);
    ipcRenderer.on('backend:lifecycle', listener);
    void (ipcRenderer.invoke('backend:get-lifecycle') as Promise<BackendLifecycleEvent | null>).then(deliver).catch(() => undefined);
    return () => ipcRenderer.removeListener('backend:lifecycle', listener);
  },
  onBrowserFind: (callback) => {
    const listener = () => callback();
    ipcRenderer.on('browser:find', listener);
    return () => ipcRenderer.removeListener('browser:find', listener);
  },
  onBrowserZoom: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, detail: { webContentsId: number; action: 'in' | 'out' | 'reset' | 'sync'; factor?: number }) => callback(detail);
    ipcRenderer.on('browser:zoom', listener);
    return () => ipcRenderer.removeListener('browser:zoom', listener);
  },
  setBrowserAddressShortcutWebContents: (webContentsId) => ipcRenderer.send('browser:address-shortcut-target', webContentsId),
  onBrowserAddressShortcut: (callback) => { const listener = () => callback(); ipcRenderer.on('browser:focus-address', listener); return () => ipcRenderer.removeListener('browser:focus-address', listener); },
};

contextBridge.exposeInMainWorld('atlasDesktop', desktopApi);
