import { useEffect, useState } from 'react';
import { AppWindow, Keyboard, MonitorUp } from 'lucide-react';
import type { GlobalShortcutState, PlatformEditorId, PlatformSettingsState, SourceUpdateStatus } from '../../../shared/ipc';

export interface PlatformSettingsPanelProps {
  workspacePath?: string | null;
  conversationId?: string | null;
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
  globalShortcut: { accelerator: null, registered: false },
};

export default function PlatformSettingsPanel({ workspacePath, conversationId }: PlatformSettingsPanelProps) {
  const desktop = window.atlasDesktop;
  const [settings, setSettings] = useState(initialState);
  const [accelerator, setAccelerator] = useState('');
  const [editor, setEditor] = useState<PlatformEditorId>('vscode');
  const [folder, setFolder] = useState(workspacePath ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [remote, setRemote] = useState('origin');
  const [branch, setBranch] = useState('');
  const [updateStatus, setUpdateStatus] = useState<SourceUpdateStatus | null>(null);

  useEffect(() => {
    if (workspacePath) setFolder(workspacePath);
  }, [workspacePath]);

  useEffect(() => {
    let active = true;
    void desktop?.getPlatformSettings?.().then((next) => {
      if (!active) return;
      setSettings(next);
      setAccelerator(next.globalShortcut.accelerator ?? '');
      setRemote(next.updateSource?.remote ?? 'origin');
      setBranch(next.updateSource?.branch ?? '');
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { active = false; };
  }, [desktop]);

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
  const perform = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null); setMessage(null);
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  return <div className="grid max-w-[760px] gap-6 text-[13px] text-fg-2">
    <div>
      <h3 className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><AppWindow size={17} />桌面平台</h3>
      <p className="mt-1 mb-0 text-[12.5px] text-fg-3">配置本机窗口行为、全局唤起快捷键和外部编辑器。</p>
    </div>

    {!available && <p role="status" className="m-0 rounded-xl border border-line p-3 text-[12px] text-fg-3">这些平台功能需要在 Atlas 桌面应用中使用。</p>}

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <h4 className="m-0 flex items-center gap-2 text-[13.5px] font-medium text-heading"><MonitorUp size={16} />窗口置顶</h4>
      <label className="flex items-center gap-2.5 text-[12.5px] text-fg-2">
        <input type="checkbox" checked={settings.alwaysOnTop} disabled={!available || busy} onChange={(event) => void toggleAlwaysOnTop(event.target.checked)} />
        Atlas 窗口始终显示在其他窗口上方
      </label>
      <label className="flex items-center gap-2.5">
        <input type="checkbox" checked={settings.trayEnabled ?? false} disabled={!desktop?.setPlatformBehavior || busy} onChange={(event) => void perform(async () => {
          setSettings(await desktop!.setPlatformBehavior!({ trayEnabled: event.target.checked, preventSleepDuringTasks: settings.preventSleepDuringTasks ?? false }));
        })} />关闭窗口时驻留系统托盘
      </label>
      <label className="flex items-center gap-2.5">
        <input type="checkbox" checked={settings.preventSleepDuringTasks ?? false} disabled={!desktop?.setPlatformBehavior || busy} onChange={(event) => void perform(async () => {
          setSettings(await desktop!.setPlatformBehavior!({ trayEnabled: settings.trayEnabled ?? false, preventSleepDuringTasks: event.target.checked }));
        })} />任务运行期间防止系统休眠
      </label>
      <p className="m-0 text-[12px] text-fg-3">托盘菜单可退出应用。任务防休眠允许显示器正常关闭，任务结束后释放。</p>
      <button disabled={!conversationId || !desktop?.openConversationWindow || busy} onClick={() => void perform(() => desktop!.openConversationWindow!(conversationId!))} className="h-9 rounded-lg border border-line px-3 text-[12px]">在独立窗口打开当前会话</button>
    </section>

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <h4 className="m-0 text-[13.5px] font-medium text-heading">源码更新来源</h4>
      <p className="m-0 text-[12px] text-fg-3">当前没有 stable/beta/nightly 签名发布 feed。源码安装可选择仓库已有 remote 与真实分支；仅支持干净工作区的快进更新。切换来源意味着信任该仓库中的代码。</p>
      <p className="m-0 text-[12px]">已保存来源：{settings.updateSource ? `${settings.updateSource.remote}/${settings.updateSource.branch}` : 'origin / 当前检出分支（默认）'}</p>
      <div className="flex flex-wrap gap-2">
        <input aria-label="更新 remote" value={remote} maxLength={64} onChange={(event) => setRemote(event.target.value)} className="h-9 rounded-lg border border-line bg-surface px-2.5" />
        <input aria-label="更新分支" value={branch} maxLength={200} placeholder="仓库真实分支名称" onChange={(event) => setBranch(event.target.value)} className="h-9 rounded-lg border border-line bg-surface px-2.5" />
        <button disabled={!desktop?.setUpdateSource || busy || !branch.trim()} onClick={() => void perform(async () => { setSettings(await desktop!.setUpdateSource!({ remote: remote.trim(), branch: branch.trim() })); setUpdateStatus(null); })} className="h-9 rounded-lg border border-line px-3">保存来源</button>
        <button disabled={!desktop?.setUpdateSource || busy} onClick={() => void perform(async () => { setSettings(await desktop!.setUpdateSource!(null)); setUpdateStatus(null); })} className="h-9 rounded-lg border border-line px-3">恢复默认</button>
        <button disabled={!desktop?.checkForUpdate || busy} onClick={() => void perform(async () => { setUpdateStatus(await desktop!.checkForUpdate!()); })} className="h-9 rounded-lg border border-line px-3">检查更新</button>
      </div>
      {updateStatus && <div role="status" className="text-[12px]">
        {updateStatus.error ?? updateStatus.blocked ?? (!updateStatus.supported ? '此安装不支持源码更新。' : `${updateStatus.branch ?? '当前分支'}：${updateStatus.behind} 个新提交`)}
        {updateStatus.commits.map((commit) => <div key={commit.hash}>{commit.hash} {commit.subject}</div>)}
      </div>}
      <button disabled={!desktop?.applyUpdate || busy || !updateStatus?.available || Boolean(updateStatus.blocked || updateStatus.error)} onClick={() => void perform(async () => { if (!await desktop!.applyUpdate!()) setError('当前状态不能应用更新。'); })} className="h-9 rounded-lg bg-brand px-3 text-on-primary disabled:opacity-50">应用更新并重启 Atlas</button>
    </section>

    <section className="grid gap-3 rounded-xl border border-line p-4">
      <div>
        <h4 className="m-0 flex items-center gap-2 text-[13.5px] font-medium text-heading"><Keyboard size={16} />全局快捷键</h4>
        <p className="mt-1 mb-0 text-[12px] text-fg-3">注册一个系统级快捷键，用于显示并聚焦 Atlas。示例：CommandOrControl+Shift+Space。</p>
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
        <p className="mt-1 mb-0 text-[12px] text-fg-3">启动 PATH 中的编辑器，或通过本机文件选择器指定编辑器程序。使用独立参数传入工作区。</p>
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
        <button disabled={!desktop?.selectEditorExecutable || busy} onClick={() => void perform(async () => { setSettings(await desktop!.selectEditorExecutable!(editor)); })} className="h-9 rounded-lg border border-line px-3">选择编辑器程序</button>
      </div>
      <p className="m-0 break-all text-[12px] text-fg-3">程序来源：{settings.editorExecutables?.[editor] ?? '系统 PATH'}</p>
    </section>

    {error && <p role="alert" className="m-0 text-[12px] text-danger">{error}</p>}
    {message && !error && <p role="status" className="m-0 text-[12px] text-fg-3">{message}</p>}
  </div>;
}
