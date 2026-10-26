/** Backend boot progress, broadcast while the desktop backend starts (H8 §10.3). */
export type BackendStartupPhase = 'probing' | 'starting' | 'ready' | 'failed';
export interface BackendStartupProgress {
  phase: BackendStartupPhase;
  /** True when this Electron session spawned the backend (vs. attaching to an external one). */
  managed: boolean;
  elapsedMs: number;
  /** Short human-readable status for the UI, e.g. which health components are still starting. */
  detail?: string;
  message?: string;
  logPath?: string;
}
/** IPC channel the main process sends {@link BackendStartupProgress} events on. */
export const BACKEND_STARTUP_CHANNEL = 'backend:startup-progress';

/** Source-mode update state (Atlas running from a git checkout). */
export interface SourceUpdateStatus {
  supported: boolean;
  available: boolean;
  behind: number;
  branch?: string;
  commits: Array<{ hash: string; subject: string }>;
  blocked?: string;
  error?: string;
}
export interface ReleaseUpdateStatus { supported: boolean; available: boolean; current: string; latest?: string; notes?: string; assetName?: string; error?: string; skipped?: boolean }

export type AtlasSettingsSection =
  | 'models' | 'advanced' | 'usage' | 'limits' | 'profiles' | 'hooks' | 'tools' | 'telegram' | 'channels'
  | 'devices' | 'localModels' | 'shortcuts' | 'appearance' | 'plugins' | 'notifications' | 'mcp'
  | 'skills' | 'recipes' | 'extensions' | 'transfer' | 'diagnostics' | 'security' | 'commands' | 'platform' | 'integrations' | 'network';

export type AtlasDeepLink =
  | { id: string; type: 'conversation'; conversationId: string }
  | { id: string; type: 'share-import'; token: string; shareUrl: string }
  | { id: string; type: 'settings'; section: AtlasSettingsSection };

export type PlatformEditorId =
  | 'vscode' | 'cursor' | 'zed' | 'idea' | 'pycharm' | 'webstorm' | 'goland' | 'rider'
  | 'clion' | 'phpstorm' | 'rubymine' | 'datagrip';

export interface GlobalShortcutState {
  accelerator: string | null;
  registered: boolean;
  error?: string;
}

export interface CaptureWindowOption { id: string; title: string; thumbnail: string }
export interface RecentScreenshot { id: string; title: string; capturedAt: number; dataUrl: string }

export interface PlatformSettingsState {
  alwaysOnTop: boolean;
  openAtLogin: boolean;
  globalShortcut: GlobalShortcutState;
  screenshotShortcut: GlobalShortcutState;
  voiceShortcut: GlobalShortcutState;
}

export interface AtlasDesktopApi {
  platform: string;
  apiBaseUrl: string;
  minimize(): void;
  maximize(): void;
  setWindowFullScreen?(enabled: boolean): Promise<boolean>;
  onWindowFullScreenChange?(callback: (fullScreen: boolean) => void): () => void;
  close(): void;
  requestQuit?(): Promise<boolean>;
  setQuitActivity?(summary: { runningTasks: number; scheduledTasks: number }): void;
  saveBugBundle?(payload: string, fileName?: string): Promise<string | null>;
  retryBackend?(): Promise<void>;
  restartBackend?(safeMode: boolean): Promise<void>;
  getSafeMode?(): Promise<boolean>;
  getSafeModePreference?(): Promise<boolean>;
  setSafeModePreference?(enabled: boolean): Promise<void>;
  openBackendLog?(): Promise<void>;
  captureHeapSnapshot?(): Promise<string | null>;
  startPerformanceTrace?(): Promise<void>;
  stopPerformanceTrace?(): Promise<string | null>;
  getSkillCenterToken(): Promise<string | undefined>;
  /** Native folder picker; resolves to the chosen absolute path, or null when cancelled. */
  selectDirectory(defaultPath?: string): Promise<string | null>;
  /** Open a file with its default app; programs and scripts are only revealed in Explorer, never run. */
  openPath(path: string): Promise<'opened' | 'revealed' | string>;
  /** Open allow-listed browser/settings URLs outside the embedded renderer. */
  openExternal?(url: string): Promise<boolean>;
  /** Produce local WAV bytes using the installed Windows SAPI voice for routable playback. */
  synthesizeSpeech?(text: string, voice: string, rate: number): Promise<string>;
  openMessageEditor?(text: string): Promise<string | null>;
  saveScreenRecording?(dataBase64: string, fileName: string): Promise<string | null>;
  deleteScreenRecording?(path: string): Promise<boolean>;
  onMaximizeChange(callback: (maximized: boolean) => void): () => void;
  /** Follow the UI theme with the window/taskbar icon ('light' | 'aurora' | 'dark'). */
  setTheme?(theme: string): void;
  /** Source mode only: compare with the remote branch. */
  checkForUpdate?(): Promise<SourceUpdateStatus>;
  /** Source mode only: quit, pull, rebuild and relaunch. Resolves false when not possible. */
  applyUpdate?(): Promise<boolean>;
  checkReleaseUpdate?(source: string): Promise<ReleaseUpdateStatus>;
  downloadReleaseUpdate?(source: string, version: string): Promise<string>;
  installReleaseUpdate?(): Promise<boolean>;
  skipReleaseVersion?(version: string): Promise<void>;
  remindReleaseLater?(): Promise<void>;
  onReleaseDownloadProgress?(callback: (percent: number) => void): () => void;
  /** Read native platform preferences and global shortcut registration state. */
  getPlatformSettings?(): Promise<PlatformSettingsState>;
  setOpenAtLogin?(enabled: boolean): Promise<PlatformSettingsState>;
  /** Persist and apply the native window's always-on-top state. */
  setAlwaysOnTop?(enabled: boolean): Promise<PlatformSettingsState>;
  /** Register a single OS-wide show/focus shortcut, or clear it with null. */
  setGlobalShortcut?(accelerator: string | null): Promise<GlobalShortcutState>;
  setScreenshotShortcut?(accelerator: string | null): Promise<GlobalShortcutState>;
  setVoiceShortcut?(accelerator: string | null): Promise<GlobalShortcutState>;
  onVoiceHotkey?(callback: () => void): () => void;
  onVoiceHotkeyStop?(callback: () => void): () => void;
  acknowledgeVoiceHotkeyStop?(): void;
  onVoiceHudResult?(callback: (transcript: string) => void): () => void;
  submitVoiceHudResult?(transcript: string): void;
  onVoiceHudStart?(callback: () => void): () => void;
  onVoiceHudStop?(callback: () => void): () => void;
  switchDataRoot?(target: string): Promise<{ restarting: boolean }>;
  setScreenshotContext?(conversationId: string, lastInteractionAt: number): void;
  onSessionScreenshot?(callback: (imageDataUrl: string, conversationId: string) => void): () => void;
  onSessionScreenshotError?(callback: (message: string) => void): () => void;
  retrySessionScreenshot?(): Promise<{ started: boolean; reason?: string }>;
  getSystemAccessStatus?(): Promise<{ platform: string; screen: string; accessibility: string; supported: boolean }>;
  requestSystemAccess?(): Promise<{ platform: string; screen: string; accessibility: string; supported: boolean }>;
  openSystemPrivacySettings?(section?: 'screen' | 'accessibility'): Promise<void>;
  setKeepAwake?(enabled: boolean): Promise<void>;
  setRuntimeState?(state: 'running' | 'waiting' | 'idle'): void;
  togglePetOverlay?(): Promise<boolean>;
  onPetOverlayStateChange?(callback: (state: 'running' | 'waiting' | 'idle') => void): () => void;
  /** Open an existing local workspace with a fixed allowlisted IDE CLI (never through a shell). */
  openWorkspaceInEditor?(editor: PlatformEditorId, workspacePath: string): Promise<void>;
  /** Open the small native floating composer. The desktop shell forwards submitted text to the main UI. */
  showFloatingComposer?(context?: { selectedText?: string; conversationId?: string }): void;
  /** Open the selected conversation in a separate synchronized desktop window. */
  openConversationWindow?(conversationId: string): void;
  openSideChatWindow?(conversationId: string, initialQuestion?: string): void;
  openNewWindow?(): void;
  openNewSessionWindow?(): void;
  listCaptureWindows?(): Promise<CaptureWindowOption[]>;
  captureWindow?(sourceId: string, conversationId: string): Promise<RecentScreenshot>;
  listRecentScreenshots?(): Promise<RecentScreenshot[]>;
  deleteRecentScreenshot?(id: string): Promise<void>;
  hideFloatingComposer?(): void;
  submitFloatingComposer?(text: string): void;
  onFloatingComposerSubmit?(callback: (text: string) => void): () => void;
  returnFloatingDraft?(text: string, conversationId?: string): void;
  onFloatingDraft?(callback: (draft: { text: string; conversationId?: string }) => void): () => void;
  onFloatingComposerContext?(callback: (context: { selectedText: string; conversationId?: string }) => void): () => void;
  getFloatingComposerContext?(): Promise<{ selectedText: string; conversationId?: string }>;
  /** Open one existing file in a fixed allowlisted IDE CLI, after validating it stays inside the workspace. */
  openFileInEditor?(editor: PlatformEditorId, workspacePath: string, filePath: string): Promise<void>;
  /** Receive validated atlas://conversation/<id> or atlas://settings/<section> routes. */
  onDeepLink?(callback: (route: AtlasDeepLink) => void): () => void;
  /** Backend startup progress (H8 §10.3): fires during boot; `ready`/`failed` are terminal. */
  onBackendStartupProgress(callback: (progress: BackendStartupProgress) => void): () => void;
  /** Receive Ctrl+F from a focused embedded page (its keyboard events do not bubble to React). */
  onBrowserFind?(callback: () => void): () => void;
}
