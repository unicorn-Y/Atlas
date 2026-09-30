/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface Window {
  atlasDesktop?: import('../shared/ipc').AtlasDesktopApi;
}

// Electron's <webview>, used by the browser panel (enabled with webviewTag in the main process).
declare namespace JSX {
  interface IntrinsicElements {
    webview: import('react').DetailedHTMLProps<import('react').HTMLAttributes<HTMLElement>, HTMLElement> & { src?: string; partition?: string; allowpopups?: string; plugins?: string };
  }
}
