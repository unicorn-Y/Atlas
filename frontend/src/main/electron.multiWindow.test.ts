import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** Regression harness for the multi-window surface (DSH-GAP D31): one window per
 * conversation, reuse instead of recreation, guarded navigation, clean close cleanup. */

const mocks = vi.hoisted(() => ({
  app: {
    isPackaged: false, isReady: vi.fn(() => false), getAppPath: vi.fn(() => '/atlas-multiwindow-test'),
    getPath: vi.fn(() => '/atlas-multiwindow-test'), getVersion: vi.fn(() => '1.0.0'),
    requestSingleInstanceLock: vi.fn(() => true), whenReady: vi.fn(() => new Promise<void>(() => undefined)),
    on: vi.fn(), quit: vi.fn(),
  },
  BrowserWindow: Object.assign(vi.fn(), { getAllWindows: vi.fn(() => []), getFocusedWindow: vi.fn() }),
  ipcMain: { on: vi.fn(), handle: vi.fn() },
  Menu: { buildFromTemplate: vi.fn((items: unknown[]) => items), setApplicationMenu: vi.fn() },
  Tray: vi.fn(function () { return { on: vi.fn(), setContextMenu: vi.fn(), setImage: vi.fn(), setToolTip: vi.fn() }; }),
  nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => true })), createEmpty: vi.fn(), createFromDataURL: vi.fn() },
  dialog: { showMessageBox: vi.fn(async () => ({ response: 0 })), showErrorBox: vi.fn() },
  shell: { openExternal: vi.fn(async () => undefined) },
  backend: {
    ensureBackendRunning: vi.fn(async () => ({ ready: true })), readRunningBackendPid: vi.fn(() => null),
    stopManagedBackend: vi.fn(async () => undefined), terminateBackendPid: vi.fn(async () => undefined),
  },
  writeFileSync: vi.fn(),
}));

vi.mock('electron', () => mocks);
vi.mock('./backendProcess.js', () => mocks.backend);
vi.mock('./stdoutSafety.js', () => ({}));
vi.mock('node:fs', async (original) => ({
  ...await original<typeof import('node:fs')>(), mkdirSync: vi.fn(), writeFileSync: mocks.writeFileSync,
}));

type FakeWin = {
  webContents: { setWindowOpenHandler: ReturnType<typeof vi.fn>; on: (event: string, handler: (...args: unknown[]) => void) => void };
  on: (event: string, handler: (...args: unknown[]) => void) => void;
  once: ReturnType<typeof vi.fn>;
  loadURL: ReturnType<typeof vi.fn>;
  loadFile: ReturnType<typeof vi.fn>;
  isDestroyed: ReturnType<typeof vi.fn>;
  isMinimized: ReturnType<typeof vi.fn>;
  restore: ReturnType<typeof vi.fn>;
  show: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
  handlers: Record<string, (...args: unknown[]) => void>;
};

const instances: FakeWin[] = [];
function makeWin(): FakeWin {
  const handlers: Record<string, (...args: unknown[]) => void> = {};
  const win: FakeWin = {
    webContents: {
      setWindowOpenHandler: vi.fn(),
      on: (event, handler) => { handlers[event] = handler; },
    },
    on: (event, handler) => { handlers[event] = handler; },
    once: vi.fn(),
    loadURL: vi.fn(async () => undefined),
    loadFile: vi.fn(async () => undefined),
    isDestroyed: vi.fn(() => false),
    isMinimized: vi.fn(() => false),
    restore: vi.fn(),
    show: vi.fn(),
    focus: vi.fn(),
    handlers,
  };
  instances.push(win);
  return win;
}

let desktop: typeof import('./electron.js');

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  instances.length = 0;
  mocks.BrowserWindow.mockImplementation(function mockWindowConstructor() { return makeWin(); } as never);
  vi.stubEnv('ATLAS_LOG_ROOT', '/atlas-multiwindow-test');
  vi.stubEnv('ATLAS_SKILL_CENTER_TOKEN', 'test-token');
  vi.stubEnv('VITE_DEV_SERVER_URL', 'http://127.0.0.1:5173');
  desktop = await import('./electron.js');
});

afterEach(() => { vi.unstubAllEnvs(); });

describe('multi-window lifecycle', () => {
  it('opens one window per conversation and focuses the existing one instead of recreating', () => {
    desktop.openConversationWindow('session_1');
    expect(mocks.BrowserWindow).toHaveBeenCalledTimes(1);
    expect(instances[0].loadURL).toHaveBeenCalledWith(expect.stringContaining('conversationId=session_1'));

    desktop.openConversationWindow('session_1');
    expect(mocks.BrowserWindow).toHaveBeenCalledTimes(1);
    expect(instances[0].focus).toHaveBeenCalledOnce();

    // A different conversation gets its own window.
    desktop.openConversationWindow('session_2');
    expect(mocks.BrowserWindow).toHaveBeenCalledTimes(2);
  });

  it('rejects invalid conversation ids before creating any window', () => {
    expect(() => desktop.openConversationWindow('bad id!')).toThrow('无效的会话 ID。');
    expect(() => desktop.openConversationWindow('../escape')).toThrow('无效的会话 ID。');
    expect(mocks.BrowserWindow).not.toHaveBeenCalled();
  });

  it('forgets a closed conversation window so the id can be reopened later', () => {
    desktop.openConversationWindow('session_1');
    const closed = instances[0].handlers['closed'];
    expect(closed).toBeTypeOf('function');
    closed();
    desktop.openConversationWindow('session_1');
    expect(mocks.BrowserWindow).toHaveBeenCalledTimes(2);
  });

  it('restores a minimized conversation window instead of spawning a new one', () => {
    desktop.openConversationWindow('session_1');
    instances[0].isMinimized.mockReturnValue(true);
    desktop.openConversationWindow('session_1');
    expect(mocks.BrowserWindow).toHaveBeenCalledTimes(1);
    expect(instances[0].restore).toHaveBeenCalledOnce();
    expect(instances[0].focus).toHaveBeenCalledOnce();
  });

  it('keeps window navigation on the app origin and sends foreign http(s) URLs to the browser', () => {
    desktop.openConversationWindow('session_1');
    const navigate = instances[0].handlers['will-navigate'];
    expect(navigate).toBeTypeOf('function');

    const blocked = { preventDefault: vi.fn() };
    navigate(blocked, 'https://evil.example.com');
    expect(blocked.preventDefault).toHaveBeenCalledOnce();
    expect(mocks.shell.openExternal).toHaveBeenCalledWith('https://evil.example.com');

    const allowed = { preventDefault: vi.fn() };
    navigate(allowed, 'http://127.0.0.1:5173/index.html#section');
    expect(allowed.preventDefault).not.toHaveBeenCalled();
    expect(mocks.shell.openExternal).not.toHaveBeenCalledWith('http://127.0.0.1:5173/index.html#section');

    const opener = instances[0].webContents.setWindowOpenHandler.mock.lastCall?.[0] as (details: { url: string }) => { action: string };
    expect(opener({ url: 'https://external.example.com/doc' })).toEqual({ action: 'deny' });
    expect(mocks.shell.openExternal).toHaveBeenCalledWith('https://external.example.com/doc');
  });
});
