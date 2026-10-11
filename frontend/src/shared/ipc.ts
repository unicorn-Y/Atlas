/** Backend boot progress, broadcast while the desktop backend starts (H8 §10.3). */
export type BackendStartupPhase = 'probing' | 'starting' | 'ready' | 'failed';
export interface BackendStartupProgress {
  phase: BackendStartupPhase;
  /** True when this Electron session spawned the backend (vs. attaching to an external one). */
  managed: boolean;
  elapsedMs: number;
  /** Short human-readable status for the UI, e.g. which health components are still starting. */
  detail?: string;
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

export type AtlasSettingsSection =
  | 'models' | 'advanced' | 'usage' | 'limits' | 'profiles' | 'hooks' | 'tools' | 'telegram' | 'channels'
  | 'devices' | 'localModels' | 'shortcuts' | 'appearance' | 'plugins' | 'notifications' | 'mcp'
  | 'skills' | 'recipes' | 'extensions' | 'transfer' | 'diagnostics' | 'telemetry' | 'security' | 'commands' | 'platform' | 'integrations' | 'network';

export type AtlasDeepLink =
  | { id: string; type: 'conversation'; conversationId: string }
  | { id: string; type: 'settings'; section: AtlasSettingsSection };

export type PlatformEditorId =
  | 'vscode' | 'idea' | 'pycharm' | 'webstorm' | 'goland' | 'rider'
  | 'clion' | 'phpstorm' | 'rubymine' | 'datagrip';

export interface GlobalShortcutState {
  accelerator: string | null;
  registered: boolean;
  error?: string;
}

export interface LocalCrashState {
  requested: boolean;
  capturing: boolean;
  restartRequired: boolean;
  reports: Array<{ id: string; size: number; modifiedAt: string }>;
}

export interface PlatformSettingsState {
  alwaysOnTop: boolean;
  globalShortcut: GlobalShortcutState;
  trayEnabled?: boolean;
  preventSleepDuringTasks?: boolean;
  sleepBlocked?: boolean;
  updateSource?: { remote: string; branch: string } | null;
  windowCount?: number;
  editorExecutables?: Partial<Record<PlatformEditorId, string>>;
}

export interface AtlasDesktopApi {
  platform: string;
  apiBaseUrl: string;
  minimize(): void;
  maximize(): void;
  close(): void;
  getSkillCenterToken(): Promise<string | undefined>;
  /** Native folder picker; resolves to the chosen absolute path, or null when cancelled. */
  selectDirectory(defaultPath?: string): Promise<string | null>;
  /** Open a file with its default app; programs and scripts are only revealed in Explorer, never run. */
  openPath(path: string): Promise<'opened' | 'revealed' | string>;
  onMaximizeChange(callback: (maximized: boolean) => void): () => void;
  /** Follow the UI theme with the window/taskbar icon ('light' | 'aurora' | 'dark'). */
  setTheme?(theme: string): void;
  /** Source mode only: compare with the remote branch. */
  checkForUpdate?(): Promise<SourceUpdateStatus>;
  /** Source mode only: quit, pull, rebuild and relaunch. Resolves false when not possible. */
  applyUpdate?(): Promise<boolean>;
  /** Read native platform preferences and global shortcut registration state. */
  getPlatformSettings?(): Promise<PlatformSettingsState>;
  /** Persist and apply the native window's always-on-top state. */
  setAlwaysOnTop?(enabled: boolean): Promise<PlatformSettingsState>;
  /** Register a single OS-wide show/focus shortcut, or clear it with null. */
  setGlobalShortcut?(accelerator: string | null): Promise<GlobalShortcutState>;
  /** Open an existing local workspace with a fixed allowlisted IDE CLI (never through a shell). */
  openWorkspaceInEditor?(editor: PlatformEditorId, workspacePath: string): Promise<void>;
  selectEditorExecutable?(editor: PlatformEditorId): Promise<PlatformSettingsState>;
  setPlatformBehavior?(settings: { trayEnabled: boolean; preventSleepDuringTasks: boolean }): Promise<PlatformSettingsState>;
  setTaskActivity?(active: boolean): Promise<void>;
  openConversationWindow?(conversationId: string): Promise<void>;
  setUpdateSource?(source: { remote: string; branch: string } | null): Promise<PlatformSettingsState>;
  setCrashCapture?(enabled: boolean): Promise<LocalCrashState>;
  getLocalCrashReports?(): Promise<LocalCrashState>;
  exportLocalCrashReport?(reportId: string): Promise<string | null>;
  /** Receive validated atlas://conversation/<id> or atlas://settings/<section> routes. */
  onDeepLink?(callback: (route: AtlasDeepLink) => void): () => void;
  /** Backend startup progress (H8 §10.3): fires during boot; `ready`/`failed` are terminal. */
  onBackendStartupProgress(callback: (progress: BackendStartupProgress) => void): () => void;
}
