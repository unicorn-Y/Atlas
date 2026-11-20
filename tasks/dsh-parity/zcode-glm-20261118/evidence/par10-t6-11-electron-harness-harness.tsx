import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Dialog } from '../../../frontend/src/renderer/ui/Dialog';
import ShortcutsPanel from '../../../frontend/src/renderer/pages/ShortcutsPanel';
import { ShortcutReferenceHost } from '../../../frontend/src/renderer/shortcuts/ShortcutReferenceHost';
import { KeybindingsProvider } from '../../../frontend/src/renderer/shortcuts/useKeybindings';

/**
 * T6-11 real-renderer probe.
 *
 * Mounts the actual host, the actual reference overlay tree, and the actual
 * ShortcutsPanel inside the real Atlas Dialog (Radix) so the Settings anchor,
 * the visible entry, the global primary+/ path and recording suppression are
 * exercised through real renderer code, not a test-only clone.
 *
 * The harness contributes only: a Settings dialog with the same close-button
 * marker App.tsx renders (`aria-label="关闭设置"`), an optional "other modal",
 * and a small App-like window keydown counter (Ctrl+K / Ctrl+,) that proves
 * the reference swallows global shortcuts while it is the top modal.
 */
function Harness() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [otherOpen, setOtherOpen] = useState(false);
  const apiBaseUrl = window.location.origin;
  return <>
    <ShortcutReferenceHost apiBaseUrl={apiBaseUrl} />
    <div id="app-surface" className="p-6">
      <h1 className="m-0 text-[18px] font-semibold text-heading">Atlas 快捷键参考探针</h1>
      <p className="mt-1 text-[12px] text-fg-3">真实 ShortcutReferenceHost + 真实 Dialog(设置) + 真实 ShortcutsPanel</p>
      <div className="mt-3 flex gap-2">
        <button id="open-settings" type="button" className="btn" onClick={() => setSettingsOpen(true)}>打开设置</button>
        <button id="open-other" type="button" className="btn" onClick={() => setOtherOpen((value) => !value)}>切换其它模态</button>
      </div>
      <pre id="probe-state" className="mt-4 text-[11px] text-fg-3">ready</pre>
    </div>
    <Dialog open={settingsOpen} onOpenChange={(open) => { if (!open) setSettingsOpen(false); }} label="设置"
      className="grid h-[min(720px,calc(100vh-48px))] w-[min(980px,calc(100vw-32px))] grid-rows-[auto_minmax(0,1fr)] gap-3 p-4">
      <div className="flex items-center gap-2">
        <h2 className="m-0 flex-1 text-[16px] font-semibold text-heading">设置</h2>
        <button aria-label="关闭设置" type="button" className="btn" onClick={() => setSettingsOpen(false)}>关闭设置</button>
      </div>
      <div className="min-h-0 overflow-auto" data-settings-content>
        <h3 className="m-0 text-[15px] font-semibold text-heading">快捷键</h3>
        <p className="mb-3 mt-1 text-[12px] text-fg-3">改成你顺手的组合键，也同步到数据目录的 keybindings.json。</p>
        <ShortcutsPanel apiBaseUrl={apiBaseUrl} />
      </div>
    </Dialog>
    {otherOpen && <div role="dialog" aria-modal="true" aria-label="其它模态"
      className="fixed inset-0 z-40 grid place-items-center bg-black/40 text-[14px] text-white">其它模态（应阻止快捷键参考）</div>}
  </>;
}

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('missing #root');
createRoot(rootElement).render(<KeybindingsProvider><Harness /></KeybindingsProvider>);

let appGlobalCount = 0;
const keyLog: Array<Record<string, unknown>> = [];
window.addEventListener('keydown', (event: KeyboardEvent) => {
  keyLog.push({ key: event.key, code: event.code, ctrlKey: event.ctrlKey, metaKey: event.metaKey, altKey: event.altKey, shiftKey: event.shiftKey, trusted: event.isTrusted, target: (event.target as HTMLElement | null)?.tagName ?? null });
  if (keyLog.length > 30) keyLog.shift();
}, true);
window.addEventListener('keydown', (event: KeyboardEvent) => {
  const globalCombo = (event.ctrlKey || event.metaKey) && !event.shiftKey
    && (event.key.toLowerCase() === 'k' || event.key === ',');
  if (!globalCombo) return;
  appGlobalCount += 1;
  const state = document.getElementById('probe-state');
  if (state) state.textContent = `app-global-count:${appGlobalCount}`;
});

(window as unknown as { __probe: unknown }).__probe = {
  appGlobalCount: () => appGlobalCount,
  keyLog: () => keyLog.slice(),
  ready: true,
};