import { useEffect, useState } from 'react';
import { AppWindow, Keyboard, MonitorUp } from 'lucide-react';
import type { GlobalShortcutState, PlatformEditorId, PlatformSettingsState } from '../../../shared/ipc';

export interface PlatformSettingsPanelProps {
  workspacePath?: string | null;
}

const EDITORS: Array<[PlatformEditorId, string]> = [
  ['vscode', 'Visual Studio Code'],
  ['idea', 'IntelliJ IDEA'],
  ['pycharm', 'PyCharm'],
  ['webstorm', 'WebStorm'],
  ['goland', 'GoLand'],
  ['rider', 'Rider'],
  ['clion', 'CLion'],
  ['phpstorm', 'PhpStorm'],
  ['rubymine', 'RubyMine'],
  ['datagrip', 'DataGrip'],
];

const initialState: PlatformSettingsState = {
  alwaysOnTop: false,
  openAtLogin: true,
  globalShortcut: { accelerator: null, registered: false },
};

export default function PlatformSettingsPanel({ workspacePath }: PlatformSettingsPanelProps) {
  const desktop = window.atlasDesktop;
  const [settings, setSettings] = useState(initialState);
  const [accelerator, setAccelerator] = useState('');
  const [editor, setEditor] = useState<PlatformEditorId>('vscode');
  const [folder, setFolder] = useState(workspacePath ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [keepAwake, setKeepAwake] = useState(() => { try { return localStorage.getItem('atlas.preference.keep-awake') === 'true'; } catch { return false; } });

  useEffect(() => {
    if (workspacePath) setFolder(workspacePath);
  }, [workspacePath]);

  useEffect(() => {
    let active = true;
    void desktop?.getPlatformSettings?.().then((next) => {
      if (!active) return;
      setSettings(next);
      setAccelerator(next.globalShortcut.accelerator ?? '');
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { active = false; };
  }, [desktop]);
  useEffect(() => {
    if (keepAwake) void desktop?.setKeepAwake?.(true).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [desktop, keepAwake]);

  const setShortcutResult = (next: GlobalShortcutState) => {
    setSettings((current) => ({ ...current, globalShortcut: next }));
    setAccelerator(next.accelerator ?? '');
    setError(null);
    setMessage(next.registered ? '全局快捷键已注册。' : next.accelerator ? null : '全局快捷键已清除。');
  };

  const toggleAlwaysOnTop = async (enabled: boolean) => {
    if (!desktop?.setAlwaysOnTop) return;
    setBusy(true); setError(null); setMessage(null);
    try { setSettings(await desktop.setAlwaysOnTop(enabled)); setMessage(enabled ? '窗口已置顶。' : '窗口已取消置顶。'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const toggleOpenAtLogin = async (enabled: boolean) => {
    if (!desktop?.setOpenAtLogin) return;
    setBusy(true); setError(null); setMessage(null);
    try {
      setSettings(await desktop.setOpenAtLogin(enabled));
      setMessage(enabled ? '已启用登录时启动 Atlas。' : '已关闭登录时启动 Atlas。');
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const toggleKeepAwake = async (enabled: boolean) => {
    if (!desktop?.setKeepAwake) return;
    setBusy(true); setError(null); setMessage(null);
    try {
      await desktop.setKeepAwake(enabled);
      setKeepAwake(enabled);
      try { localStorage.setItem('atlas.preference.keep-awake', String(enabled)); } catch { /* preference remains active for this session */ }
      setMessage(enabled ? '运行任务时将阻止系统自动休眠。' : '运行任务时允许系统自动休眠。');
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const saveShortcut = async (value: string | null) => {
    if (!desktop?.setGlobalShortcut) return;
    setBusy(true); setError(null); setMessage(null);
    try { setShortcutResult(await desktop.setGlobalShortcut(value)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const selectWorkspace = async () => {
    try {
      const selected = await desktop?.selectDirectory(folder || undefined);
      if (selected) { setFolder(selected); setError(null); setMessage(null); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  };

  const openInEditor = async () => {
    if (!desktop?.openWorkspaceInEditor) return;
    if (!folder.trim()) { setError('请选择要打开的工作区目录。'); return; }
    setBusy(true); setError(null); setMessage(null);
    try {
      await desktop.openWorkspaceInEditor(editor, folder.trim());
      setMessage(`已使用 ${EDITORS.find(([id]) => id === editor)?.[1] ?? editor} 打开工作区。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const available = Boolean(desktop?.getPlatformSettings);
  return <div className="grid max-w-[760px] gap-6 text-[13px] text-fg-2">
    <div>
      <h3 className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><AppWindow size={17} />桌面平台</h3>
      <p className="mt-1 mb-0 text-[12.5px] text-fg-3">配置本机窗口行为、全局唤起快捷键和外部编辑器。</p>
    </div>

    {!available && <p role="status" className="m-0 rounded-xl border border-line p-3 text-[12px] text-fg-3">这些平台功能需要在 Atlas 桌面应用中使用。</p>}

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <h4 className="m-0 text-[13.5px] font-medium text-heading">任务运行时防休眠</h4>
      <label className="flex items-center gap-2.5 text-[12.5px] text-fg-2">
        <input type="checkbox" checked={keepAwake} disabled={!available || !desktop?.setKeepAwake || busy} onChange={(event) => void toggleKeepAwake(event.target.checked)} />
        运行中的任务阻止系统自动休眠
      </label>
    </section>

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <h4 className="m-0 text-[13.5px] font-medium text-heading">登录时启动</h4>
      <label className="flex items-center gap-2.5 text-[12.5px] text-fg-2">
        <input type="checkbox" checked={settings.openAtLogin} disabled={!available || !desktop?.setOpenAtLogin || busy} onChange={(event) => void toggleOpenAtLogin(event.target.checked)} />
        登录时启动 Atlas
      </label>
    </section>

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <h4 className="m-0 flex items-center gap-2 text-[13.5px] font-medium text-heading"><MonitorUp size={16} />窗口置顶</h4>
      <label className="flex items-center gap-2.5 text-[12.5px] text-fg-2">
        <input type="checkbox" checked={settings.alwaysOnTop} disabled={!available || busy} onChange={(event) => void toggleAlwaysOnTop(event.target.checked)} />
        Atlas 窗口始终显示在其他窗口上方
      </label>
    </section>

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <div>
        <h4 className="m-0 flex items-center gap-2 text-[13.5px] font-medium text-heading"><Keyboard size={16} />全局快捷键</h4>
        <p className="mt-1 mb-0 text-[12px] text-fg-3">注册系统级快捷键呼出浮动输入条；提交后发送到当前对话，没有当前对话时会新建一条。示例：CommandOrControl+Shift+Space。</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <input aria-label="全局快捷键" value={accelerator} maxLength={80} disabled={!available || busy} onChange={(event) => setAccelerator(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void saveShortcut(accelerator); }} placeholder="CommandOrControl+Shift+Space" className="h-9 min-w-[250px] flex-1 rounded-lg border border-line bg-surface px-2.5 font-mono text-[12px] text-fg" />
        <button disabled={!available || busy || !accelerator.trim()} onClick={() => void saveShortcut(accelerator)} className="h-9 rounded-lg bg-brand px-3 text-[12px] font-medium text-on-primary disabled:opacity-50">注册</button>
        <button disabled={!available || busy || !settings.globalShortcut.accelerator} onClick={() => void saveShortcut(null)} className="h-9 rounded-lg border border-line px-3 text-[12px] text-fg-2 hover:bg-hover disabled:opacity-50">清除</button>
      </div>
      <p role={settings.globalShortcut.error ? 'alert' : 'status'} className={`m-0 text-[12px] ${settings.globalShortcut.error ? 'text-danger' : 'text-fg-3'}`}>
        {settings.globalShortcut.error ?? (settings.globalShortcut.registered ? `已注册：${settings.globalShortcut.accelerator}` : settings.globalShortcut.accelerator ? `未注册：${settings.globalShortcut.accelerator}` : '尚未注册')}
      </p>
    </section>

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <div>
        <h4 className="m-0 text-[13.5px] font-medium text-heading">在编辑器中打开工作区</h4>
        <p className="mt-1 mb-0 text-[12px] text-fg-3">仅启动本机已安装且已加入 PATH 的编辑器命令。</p>
      </div>
      <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
        <input aria-label="工作区目录" value={folder} onChange={(event) => setFolder(event.target.value)} placeholder="选择本地工作区目录" className="h-9 min-w-0 rounded-lg border border-line bg-surface px-2.5 text-[12px] text-fg" />
        <button disabled={!available || busy} onClick={() => void selectWorkspace()} className="h-9 rounded-lg border border-line px-3 text-[12px] text-fg-2 hover:bg-hover disabled:opacity-50">选择目录</button>
      </div>
      <div className="flex flex-wrap gap-2">
        <select aria-label="编辑器" value={editor} onChange={(event) => setEditor(event.target.value as PlatformEditorId)} className="h-9 min-w-[190px] flex-1 rounded-lg border border-line bg-surface px-2.5 text-[12px] text-fg">
          {EDITORS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
        <button disabled={!available || busy || !folder.trim()} onClick={() => void openInEditor()} className="h-9 rounded-lg bg-brand px-3 text-[12px] font-medium text-on-primary disabled:opacity-50">打开工作区</button>
      </div>
    </section>

    {error && <p role="alert" className="m-0 text-[12px] text-danger">{error}</p>}
    {message && !error && <p role="status" className="m-0 text-[12px] text-fg-3">{message}</p>}
  </div>;
}
