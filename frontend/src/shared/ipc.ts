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
  /** Backend startup progress (H8 §10.3): fires during boot; `ready`/`failed` are terminal. */
  onBackendStartupProgress(callback: (progress: BackendStartupProgress) => void): () => void;
}
