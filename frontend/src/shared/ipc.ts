export interface AtlasDesktopApi {
  platform: string;
  apiBaseUrl: string;
  minimize(): void;
  maximize(): void;
  close(): void;
  getSkillCenterToken(): Promise<string | undefined>;
  /** Native folder picker; resolves to the chosen absolute path, or null when cancelled. */
  selectDirectory(defaultPath?: string): Promise<string | null>;
  onMaximizeChange(callback: (maximized: boolean) => void): () => void;
}
