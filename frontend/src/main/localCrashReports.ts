import { app, crashReporter, dialog, type BrowserWindow } from 'electron';
import { copyFileSync, lstatSync, readdirSync, realpathSync } from 'node:fs';
import path from 'node:path';
import type { LocalCrashState } from '../shared/ipc.js';

let requested = false;
let capturing = false;

export function setCrashCapture(enabled: boolean): LocalCrashState {
  requested = enabled;
  if (enabled && !capturing) {
    crashReporter.start({ productName: 'Atlas', companyName: 'Atlas', submitURL: '', uploadToServer: false, ignoreSystemCrashHandler: false });
    capturing = true;
  }
  if (capturing) crashReporter.setUploadToServer(false);
  // Electron cannot stop an initialized Crashpad client until this process exits.
  return localCrashState();
}

function reportFiles(): Map<string, string> {
  const files = new Map<string, string>();
  const root = app.getPath('crashDumps');
  for (const folder of ['', 'pending', 'completed', 'reports']) {
    const dir = path.join(root, folder);
    try {
      if (lstatSync(dir).isSymbolicLink()) continue;
      for (const entry of readdirSync(dir, { withFileTypes: true }).slice(0, 500)) {
        if (!entry.isFile() || !/^[A-Za-z0-9_-]+\.dmp$/.test(entry.name)) continue;
        const file = path.join(dir, entry.name);
        const relative = path.relative(realpathSync(root), realpathSync(file));
        if (relative.startsWith('..') || path.isAbsolute(relative)) continue;
        files.set(`${folder || 'root'}:${entry.name}`, file);
      }
    } catch { /* missing crash directory has no reports */ }
  }
  return files;
}

export function localCrashState(): LocalCrashState {
  return { requested, capturing, restartRequired: capturing && !requested,
    reports: [...reportFiles()].map(([id, file]) => { const stat = lstatSync(file); return { id, size: stat.size, modifiedAt: stat.mtime.toISOString() }; }).sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt)).slice(0, 100) };
}

export async function exportLocalCrashReport(owner: BrowserWindow, id: string): Promise<string | null> {
  const file = reportFiles().get(id);
  if (!file) throw new Error('崩溃报告不存在。');
  const result = await dialog.showSaveDialog(owner, { title: '导出本地崩溃报告（可能包含运行时内存）', defaultPath: path.basename(file), filters: [{ name: 'Crash dump', extensions: ['dmp'] }] });
  if (result.canceled || !result.filePath) return null;
  if (reportFiles().get(id) !== file) throw new Error('崩溃报告已变化。');
  copyFileSync(file, result.filePath);
  return result.filePath;
}

export async function loadCrashPrivacy(apiBaseUrl: string): Promise<void> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/settings-audit/privacy`, {
      headers: { 'X-Atlas-Api-Token': process.env.ATLAS_API_TOKEN ?? '' }, signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return;
    const value = await response.json() as { crash_capture_enabled?: unknown };
    if (typeof value.crash_capture_enabled === 'boolean') setCrashCapture(value.crash_capture_enabled);
  } catch { /* privacy unavailable: capture stays off */ }
}
