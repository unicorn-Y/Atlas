import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const electronMocks = vi.hoisted(() => {
  const window = {
    on: vi.fn(),
    minimize: vi.fn(),
    maximize: vi.fn(),
    unmaximize: vi.fn(),
    close: vi.fn(),
    isMaximized: vi.fn(() => false),
    loadURL: vi.fn(),
    loadFile: vi.fn(),
    webContents: {
      on: vi.fn(),
      send: vi.fn(),
      setWindowOpenHandler: vi.fn(),
      loadURL: vi.fn(),
      reload: vi.fn(),
    },
  };
  const BrowserWindow = Object.assign(
    vi.fn(function BrowserWindowMock() { return window; }),
    {
      fromWebContents: vi.fn(() => window),
      getAllWindows: vi.fn(() => [window]),
    },
  );
  return {
    window,
    BrowserWindow,
    app: {
      isPackaged: false,
      whenReady: vi.fn(() => Promise.resolve()),
      on: vi.fn(),
      quit: vi.fn(),
    },
    dialog: { showOpenDialog: vi.fn() },
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: { setApplicationMenu: vi.fn() },
    session: { defaultSession: { webRequest: { onBeforeSendHeaders: vi.fn() } } },
    shell: { openExternal: vi.fn(), openPath: vi.fn(), showItemInFolder: vi.fn() },
  };
});

vi.mock('electron', () => electronMocks);
vi.mock('./backendProcess.js', () => ({
  ensureBackendRunning: vi.fn(async () => ({ ready: true, managed: false })),
  stopManagedBackend: vi.fn(async () => undefined),
}));

describe('Electron development navigation trust', () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.stubEnv('VITE_DEV_SERVER_URL', 'http://127.0.0.1:5173');
    await import('./electron.js');
    await vi.waitFor(() => expect(electronMocks.BrowserWindow).toHaveBeenCalled());
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('blocks a URL whose text starts with the dev origin but whose parsed origin is different', () => {
    const navigate = electronMocks.window.webContents.on.mock.calls
      .find(([event]) => event === 'will-navigate')?.[1] as
      ((event: { preventDefault: () => void }, url: string) => void) | undefined;
    expect(navigate).toBeTypeOf('function');

    const event = { preventDefault: vi.fn() };
    navigate?.(event, 'http://127.0.0.1:5173@attacker.example/');

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(electronMocks.shell.openExternal).toHaveBeenCalledWith('http://127.0.0.1:5173@attacker.example/');
  });

  it('allows pages served from the exact dev origin', () => {
    const navigate = electronMocks.window.webContents.on.mock.calls
      .find(([event]) => event === 'will-navigate')?.[1] as
      ((event: { preventDefault: () => void }, url: string) => void) | undefined;
    expect(navigate).toBeTypeOf('function');

    const event = { preventDefault: vi.fn() };
    navigate?.(event, 'http://127.0.0.1:5173/settings');

    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});
