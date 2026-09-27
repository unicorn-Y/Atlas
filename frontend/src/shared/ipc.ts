export interface AtlasDesktopApi {
  platform: string;
  apiBaseUrl: string;
  minimize(): void;
  maximize(): void;
  close(): void;
  getSkillCenterToken(): Promise<string | undefined>;
  onMaximizeChange(callback: (maximized: boolean) => void): () => void;
}
