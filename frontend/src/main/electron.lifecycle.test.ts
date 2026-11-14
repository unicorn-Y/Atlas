import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BrowserWindow } from 'electron';

const mocks = vi.hoisted(() => {
  const tray = { on: vi.fn(), setContextMenu: vi.fn(), setImage: vi.fn(), setToolTip: vi.fn() };
  return {
    tray,
    app: {
      isPackaged: false, isReady: vi.fn(() => false), getAppPath: vi.fn(() => '/atlas-frontend'),
      getPath: vi.fn(() => '/atlas-lifecycle-test'), getVersion: vi.fn(() => '1.0.0'),
      requestSingleInstanceLock: vi.fn(() => true), whenReady: vi.fn(() => new Promise<void>(() => undefined)),
      on: vi.fn(), quit: vi.fn(),
    },
    BrowserWindow: { getAllWindows: vi.fn(() => []), getFocusedWindow: vi.fn() },
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: { buildFromTemplate: vi.fn((items: unknown[]) => items), setApplicationMenu: vi.fn() },
    Tray: vi.fn(function () { return tray; }),
    nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => true })), createEmpty: vi.fn(), createFromDataURL: vi.fn() },
    dialog: { showMessageBox: vi.fn(async () => ({ response: 0 })) },
    backend: {
      ensureBackendRunning: vi.fn(async () => ({ ready: true })), readRunningBackendPid: vi.fn(() => null),
      stopManagedBackend: vi.fn(async () => undefined), terminateBackendPid: vi.fn(async () => undefined),
    },
    writeFileSync: vi.fn(),
  };
});

vi.mock('electron', () => mocks);
vi.mock('./backendProcess.js', () => mocks.backend);
vi.mock('./stdoutSafety.js', () => ({}));
vi.mock('node:fs', async (original) => ({
  ...await original<typeof import('node:fs')>(), mkdirSync: vi.fn(), writeFileSync: mocks.writeFileSync,
}));

let desktop: typeof import('./electron.js');

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  mocks.app.requestSingleInstanceLock.mockReturnValue(true);
  mocks.dialog.showMessageBox.mockResolvedValue({ response: 0 });
  vi.stubEnv('ATLAS_LOG_ROOT', '/atlas-lifecycle-test');
  vi.stubEnv('ATLAS_SKILL_CENTER_TOKEN', 'test-token');
  desktop = await import('./electron.js');
});

afterEach(() => vi.unstubAllEnvs());

describe('desktop lifecycle components', () => {
  it('quits the second process and registers deep-link entry points only for the owner', async () => {
    expect(mocks.app.requestSingleInstanceLock).toHaveBeenCalledOnce();
    expect(mocks.app.on.mock.calls.map(([event]) => event)).toContain('second-instance');
    expect(mocks.app.on.mock.calls.map(([event]) => event)).toContain('open-url');

    vi.resetModules();
    vi.clearAllMocks();
    mocks.app.requestSingleInstanceLock.mockReturnValue(false);
    await import('./electron.js');
    expect(mocks.app.quit).toHaveBeenCalledOnce();
    expect(mocks.app.on.mock.calls.map(([event]) => event)).not.toContain('second-instance');
  });

  it('accepts conversation/settings deep links and rejects ambiguous or credentialed URLs', () => {
    expect(desktop.parseAtlasDeepLink('atlas://conversation/session_1?draft=hello')).toMatchObject({
      type: 'conversation', conversationId: 'session_1', draft: 'hello',
    });
    expect(desktop.parseAtlasDeepLink('atlas://settings/plugins')).toMatchObject({ type: 'settings', section: 'plugins' });
    for (const url of ['atlas://user:pass@conversation/id', 'atlas://conversation/id?draft=a&draft=b', 'atlas://settings/unknown', 'atlas://conversation/id#hidden']) {
      expect(desktop.parseAtlasDeepLink(url)).toBeNull();
    }
  });

  it('builds a persistent tray with backend status, recovery, open and explicit quit actions', () => {
    desktop.createTray();
    desktop.createTray();
    expect(mocks.Tray).toHaveBeenCalledOnce();
    expect(mocks.tray.on).toHaveBeenCalledWith('double-click', expect.any(Function));
    const items = mocks.tray.setContextMenu.mock.lastCall?.[0] as Array<{ label?: string; enabled?: boolean; click?: () => void }>;
    expect(items.map((item) => item.label)).toEqual(expect.arrayContaining(['打开 Atlas', '后台组件', '以安全模式重启', '重启后台', '退出 Atlas']));
    expect(items.some((item) => item.label?.startsWith('后台：') && item.enabled === false)).toBe(true);
    const closed = mocks.app.on.mock.calls.find(([event]) => event === 'window-all-closed')?.[1] as () => void;
    closed();
    expect(mocks.app.quit).not.toHaveBeenCalled();
    items.find((item) => item.label === '退出 Atlas')?.click?.();
    expect(mocks.app.quit).toHaveBeenCalledOnce();
  });

  it('registers native editing roles and nonconflicting window accelerators', () => {
    desktop.createApplicationMenu();
    const menu = mocks.Menu.setApplicationMenu.mock.lastCall?.[0] as Array<{ label?: string; submenu: Array<{ label?: string; accelerator?: string; role?: string }> }>;
    const file = menu.find((item) => item.label === '文件')?.submenu ?? [];
    expect(file.find((item) => item.label === '新建窗口')?.accelerator).toBe('CommandOrControl+Shift+N');
    expect(file.find((item) => item.label === '新会话并在新窗口打开')?.accelerator).toBe('CommandOrControl+Alt+N');
    expect(file.find((item) => item.label === '关闭当前窗口')?.accelerator).toBeUndefined();
    expect(menu.find((item) => item.label === '编辑')?.submenu.map((item) => item.role)).toEqual(expect.arrayContaining(['undo', 'redo', 'cut', 'copy', 'paste', 'selectAll']));
  });

  it('recovers a renderer crash through an explicit plugin-disabled backend restart', async () => {
    mocks.dialog.showMessageBox.mockResolvedValue({ response: 1 });
    const win = { isDestroyed: () => false, webContents: { reload: vi.fn() } };
    await desktop.recoverRendererCrash(win as unknown as BrowserWindow, { reason: 'crashed', exitCode: 1 });
    expect(mocks.dialog.showMessageBox).toHaveBeenCalledWith(win, expect.objectContaining({ buttons: ['重新加载', '禁用全部插件并重启', '稍后'] }));
    expect(mocks.backend.stopManagedBackend).toHaveBeenCalledWith('renderer_crash_safe_mode');
    expect(mocks.backend.ensureBackendRunning).toHaveBeenCalledWith(expect.objectContaining({ safeMode: true }));
    expect(mocks.writeFileSync.mock.calls.some(([, content]) => String(content).includes('"safeModeOnNextStart": true'))).toBe(true);
    expect(win.webContents.reload).toHaveBeenCalledOnce();
  });

  it('lets recovery be deferred and ignores clean renderer exits', async () => {
    const win = { isDestroyed: () => false, webContents: { reload: vi.fn() } };
    mocks.dialog.showMessageBox.mockResolvedValue({ response: 2 });
    await desktop.recoverRendererCrash(win as unknown as BrowserWindow, { reason: 'crashed', exitCode: 1 });
    await desktop.recoverRendererCrash(win as unknown as BrowserWindow, { reason: 'clean-exit', exitCode: 0 });
    expect(mocks.dialog.showMessageBox).toHaveBeenCalledOnce();
    expect(mocks.backend.stopManagedBackend).not.toHaveBeenCalled();
    expect(win.webContents.reload).not.toHaveBeenCalled();
  });
});
