export interface AtlasDesktopApi {
  platform: string;
  minimize(): void;
  maximize(): void;
  close(): void;
  onMaximizeChange(callback: (maximized: boolean) => void): () => void;
}
