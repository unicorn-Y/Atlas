import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BrowserWindow } from 'electron';
import type { BackendLifecycleEvent } from '../shared/ipc.js';

// D2: the main process publishes typed lifecycle states (ready / fatal /
// shutdown-complete / quit-inspection) over one channel, and ipcMain serves the
// latest event so a subscribing renderer can catch up. This harness boots the
// real app.whenReady flow (only electron + backendProcess are mocked) and reads
// the events the main window actually receives.

const mocks = vi.hoisted(() => ({
  app: {
    isPackaged: false, isReady: vi.fn(() => true), getAppPath: vi.fn(() => '/atlas-lifecycle-boot'),
    getPath: vi.fn(() => '/atlas-lifecycle-boot'), getVersion: vi.fn(() => '1.0.0'),
    requestSingleInstanceLock: vi.fn(() => true), whenReady: vi.fn(() => Promise.resolve()),
    on: vi.fn(), quit: vi.fn(), exit: vi.fn(),
    setLoginItemSettings: vi.fn(), setAsDefaultProtocolClient: vi.fn(),
  },
  BrowserWindow: Object.assign(vi.fn(), {
    getAllWindows: vi.fn(() => []), getFocusedWindow: vi.fn(), fromWebContents: vi.fn(),
  }),
  ipcMain: { on: vi.fn(), handle: vi.fn() },
  Menu: { buildFromTemplate: vi.fn((items: unknown[]) => items), setApplicationMenu: vi.fn() },
  Tray: vi.fn(function () {
    return { on: vi.fn(), setContextMenu: vi.fn(), setImage: vi.fn(), setToolTip: vi.fn() };
  }),
  nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => true })), createEmpty: vi.fn(), createFromDataURL: vi.fn() },
  dialog: { showMessageBox: vi.fn(async () => ({ response: 0 })), showErrorBox: vi.fn() },
  shell: { openExternal: vi.fn(async () => undefined) },
  globalShortcut: { register: vi.fn(() => true), unregister: vi.fn(), unregisterAll: vi.fn() },
  session: { defaultSession: { webRequest: { onBeforeSendHeaders: vi.fn() } } },
  powerSaveBlocker: { isStarted: vi.fn(() => false), start: vi.fn(() => 1), stop: vi.fn() },
  screen: { getAllDisplays: vi.fn(() => []), getPrimaryDisplay: vi.fn(() => ({ workArea: { x: 0, y: 0, width: 1920, height: 1080 } })), on: vi.fn() },
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
  ...await original<typeof import('node:fs')>(),
  mkdirSync: vi.fn(), writeFileSync: mocks.writeFileSync, chmodSync: vi.fn(),
}));

type FakeWin = {
  webContents: {
    send: ReturnType<typeof vi.fn>;
    setWindowOpenHandler: ReturnType<typeof vi.fn>;
    on: (event: string, handler: (...args: unknown[]) => void) => void;
    mainFrame: { url: string };
  };
  on: (event: string, handler: (...args: unknown[]) => void) => void;
  once: ReturnType<typeof vi.fn>;
  loadURL: ReturnType<typeof vi.fn>;
  loadFile: ReturnType<typeof vi.fn>;
  isDestroyed: ReturnType<typeof vi.fn>;
  isMinimized: ReturnType<typeof vi.fn>;
  restore: ReturnType<typeof vi.fn>;
  show: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
  setAlwaysOnTop: ReturnType<typeof vi.fn>;
};

const instances: FakeWin[] = [];
function makeWin(): FakeWin {
  const handlers: Record<string, (...args: unknown[]) => void> = {};
  const win: FakeWin = {
    webContents: {
      send: vi.fn(),
      setWindowOpenHandler: vi.fn(),
      on: (event, handler) => { handlers[event] = handler; },
      mainFrame: { url: 'http://127.0.0.1:5173/' },
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
    setAlwaysOnTop: vi.fn(),
  };
  instances.push(win);
  return win;
}

const BACKEND_LIFECYCLE_CHANNEL = 'backend:lifecycle';

/** Lifecycle frames the main window actually received, in publication order. */
function lifecycleEvents(): BackendLifecycleEvent[] {
  const win = instances[0];
  if (!win) return [];
  return win.webContents.send.mock.calls
    .filter(([channel]) => channel === BACKEND_LIFECYCLE_CHANNEL)
    .map(([, event]) => event as BackendLifecycleEvent);
}

function ipcHandler(name: string): (event: unknown, ...rest: unknown[]) => unknown {
  const call = mocks.ipcMain.handle.mock.calls.find(([channel]) => channel === name);
  if (!call) throw new Error(`ipc handler not registered: ${name}`);
  return call[1] as (event: unknown, ...rest: unknown[]) => unknown;
}

function ipcListener(name: string): (event: unknown, ...rest: unknown[]) => void {
  const call = mocks.ipcMain.on.mock.calls.find(([channel]) => channel === name);
  if (!call) throw new Error(`ipc listener not registered: ${name}`);
  return call[1] as (event: unknown, ...rest: unknown[]) => void;
}

/** An invoke event from the main window's own webContents (assertTrustedAppSender must pass). */
function trustedEvent(): { sender: FakeWin['webContents']; senderFrame: { url: string } } {
  const sender = instances[0]?.webContents;
  if (!sender) throw new Error('main window was not created during boot');
  return { sender, senderFrame: sender.mainFrame };
}

async function bootComplete(): Promise<void> {
  await vi.waitFor(() => {
    expect(mocks.dialog.showErrorBox).not.toHaveBeenCalled();
    expect(lifecycleEvents().some((event) => event.kind === 'ready')).toBe(true);
  }, { timeout: 5000, interval: 25 });
}

let desktop: typeof import('./electron.js');

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  instances.length = 0;
  mocks.BrowserWindow.mockImplementation(function mockWindowConstructor() { return makeWin(); } as never);
  mocks.BrowserWindow.fromWebContents.mockImplementation((sender: unknown) => (
    sender && sender === instances[0]?.webContents ? (instances[0] as unknown as BrowserWindow) : null
  ));
  mocks.backend.ensureBackendRunning.mockResolvedValue({ ready: true } as never);
  mocks.backend.readRunningBackendPid.mockReturnValue(null);
  mocks.backend.stopManagedBackend.mockResolvedValue(undefined);
  mocks.dialog.showMessageBox.mockResolvedValue({ response: 0 } as never);
  // The tray refresh interval must not keep timers pending across tests.
  vi.stubGlobal('setInterval', vi.fn(() => 123));
  vi.stubGlobal('clearInterval', vi.fn());
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ components: {} }) })));
  vi.stubEnv('ATLAS_LOG_ROOT', '/atlas-lifecycle-boot');
  vi.stubEnv('VITE_DEV_SERVER_URL', 'http://127.0.0.1:5173');
  vi.stubEnv('ATLAS_SKILL_CENTER_TOKEN', 'test-token');
  desktop = await import('./electron.js');
  return desktop;
});

afterEach(() => vi.unstubAllEnvs());

describe('desktop backend lifecycle publishing (D2)', () => {
  it('publishes a typed ready event to the window once the backend attached', async () => {
    await bootComplete();
    const events = lifecycleEvents();
    const ready = events.find((event) => event.kind === 'ready');
    expect(ready).toMatchObject({ kind: 'ready' });
    expect(typeof ready?.sequence).toBe('number');
    expect(Number.isNaN(Date.parse(ready?.timestamp ?? ''))).toBe(false);
    // The boot itself stayed healthy: no error dialog, no forced exit.
    expect(mocks.dialog.showErrorBox).not.toHaveBeenCalled();
    expect(mocks.app.exit).not.toHaveBeenCalled();
    expect(desktop).toBeDefined();
  });

  it('sequences lifecycle states monotonically and serves the latest on subscription', async () => {
    await bootComplete();
    mocks.backend.ensureBackendRunning.mockRejectedValueOnce(new Error('backend exploded'));
    void ipcHandler('backend:retry')(trustedEvent());
    await vi.waitFor(() => expect(lifecycleEvents().some((event) => event.kind === 'fatal')).toBe(true), { timeout: 5000, interval: 25 });

    const events = lifecycleEvents();
    expect(events.map((event) => event.kind)).toEqual(['ready', 'shutdown-complete', 'fatal']);
    const sequences = events.map((event) => event.sequence);
    expect([...sequences].sort((a, b) => a - b)).toEqual(sequences);
    expect(new Set(sequences).size).toBe(sequences.length);

    const fatal = events.at(-1);
    expect(fatal).toMatchObject({ kind: 'fatal', detail: 'backend exploded' });
    await expect(Promise.resolve(ipcHandler('backend:get-lifecycle')(trustedEvent()))).resolves.toEqual(fatal);
  });

  it('publishes quit-inspection with the reported activity before asking the user', async () => {
    await bootComplete();
    ipcListener('app:set-quit-activity')(trustedEvent(), { runningTasks: 1, scheduledTasks: 2 });
    await expect(Promise.resolve(ipcHandler('app:quit-request')(trustedEvent()))).resolves.toBe(true);

    const events = lifecycleEvents();
    const quitInspection = events.find((event) => event.kind === 'quit-inspection');
    expect(quitInspection).toMatchObject({ kind: 'quit-inspection', runningTasks: 1, scheduledTasks: 2 });
    // Activity was reported, so the user is asked before the app quits.
    expect(mocks.dialog.showMessageBox).toHaveBeenCalledWith(
      instances[0] as unknown as BrowserWindow,
      expect.objectContaining({ buttons: ['退出并中断任务', '取消'] }),
    );
    expect(mocks.app.quit).toHaveBeenCalledOnce();
  });
});
