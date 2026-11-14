import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const electronMocks = vi.hoisted(() => {
  const window = {
    on: vi.fn(),
    once: vi.fn(),
    minimize: vi.fn(),
    maximize: vi.fn(),
    unmaximize: vi.fn(),
    close: vi.fn(),
    isMaximized: vi.fn(() => false),
    isDestroyed: vi.fn(() => false),
    setAlwaysOnTop: vi.fn(),
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
  const tray = { on: vi.fn(), setContextMenu: vi.fn(), setImage: vi.fn(), setToolTip: vi.fn() };
  const BrowserWindow = Object.assign(
    vi.fn(function BrowserWindowMock() { return window; }),
    {
      fromWebContents: vi.fn(() => window),
      getAllWindows: vi.fn(() => [window]),
    },
  );
  return {
    window,
    tray,
    BrowserWindow,
    app: {
      isPackaged: false,
      getAppPath: vi.fn(() => '/atlas-frontend'),
      getPath: vi.fn(() => '/atlas-test-user-data'),
      requestSingleInstanceLock: vi.fn(() => true),
      setAsDefaultProtocolClient: vi.fn(),
      setLoginItemSettings: vi.fn(),
      whenReady: vi.fn(() => Promise.resolve()),
      on: vi.fn(),
      quit: vi.fn(),
      exit: vi.fn(),
    },
    dialog: { showOpenDialog: vi.fn(), showErrorBox: vi.fn(), showMessageBox: vi.fn(async () => ({ response: 0 })) },
    globalShortcut: { register: vi.fn(() => true), unregister: vi.fn(), unregisterAll: vi.fn() },
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: { buildFromTemplate: vi.fn((items: unknown[]) => items), setApplicationMenu: vi.fn() },
    nativeImage: {
      createFromPath: vi.fn(() => ({ isEmpty: () => true })),
      createEmpty: vi.fn(),
      createFromDataURL: vi.fn(),
    },
    powerSaveBlocker: { isStarted: vi.fn(() => false), start: vi.fn(() => 1), stop: vi.fn() },
    Tray: vi.fn(function TrayMock() { return tray; }),
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
    // Isolate the boot's preference/token reads and keep the tray timer from staying pending.
    vi.stubEnv('ATLAS_DATA_DIR', '/atlas-navigation-test');
    vi.stubGlobal('setInterval', vi.fn(() => 123));
    vi.stubGlobal('clearInterval', vi.fn());
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ components: {} }) })));
    await import('./electron.js');
    // The boot must actually reach window creation (it used to die inside an incomplete mock).
    await vi.waitFor(() => expect(electronMocks.BrowserWindow).toHaveBeenCalled(), { timeout: 5000, interval: 25 });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
