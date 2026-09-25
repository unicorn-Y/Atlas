/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface Window {
  atlasDesktop?: import('../shared/ipc').AtlasDesktopApi;
}
