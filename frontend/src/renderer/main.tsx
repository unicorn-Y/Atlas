import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/noto-serif-sc/400.css';
import '@fontsource/noto-serif-sc/600.css';
import '@fontsource/noto-serif-sc/700.css';
import './ui/inputModality';
import App from './App';
import { useAtlasStore } from './store/useAtlasStore';
import './styles/app.css';

// Dev-only handle for inspecting app state from the devtools console.
if (import.meta.env.DEV) (window as unknown as { __atlas: typeof useAtlasStore }).__atlas = useAtlasStore;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
