export interface AtlasDesktopApi {
  platform: string;
  minimize(): void;
  maximize(): void;
  close(): void;
  getSkillCenterToken(): Promise<string | undefined>;
  onMaximizeChange(callback: (maximized: boolean) => void): () => void;
}
