import { api } from './api';

/**
 * X2（电脑操控 / 浏览器代理）后端路由的类型化客户端，沿用 services/api.ts 的 fetch 约定：
 * 非 2xx 抛出带中文 detail 的 Error，204 视为无返回体。组件只拿 apiBaseUrl 就能调用。
 */

// ---------- 电脑操控 ----------

/** GET /api/computer/status 的返回：就绪状态、驱动与逐项诊断。 */
export interface ComputerStatus {
  ready: boolean;
  /** 后端实际使用的操控驱动（如 cua / pywinauto），缺省时只显示就绪与否。 */
  driver?: string;
  /** 未就绪时的原因说明。 */
  detail?: string;
  diagnostics?: ComputerDiagnostic[];
}

export interface ComputerDiagnostic {
  name?: string;
  ok?: boolean;
  detail?: string;
}

/** GET /api/computer/runs/{run_id}/steps 的一条步骤：动作说明 + 可选截图缩略。 */
export interface ComputerStep {
  index?: number;
  action: string;
  target?: string;
  /** 截图缩略（data URL 或后端可访问地址），缺省时只显示文字。 */
  thumbnail?: string;
  timestamp?: string;
}

export const resolveForeground = (apiBaseUrl: string, runId: string, approve: boolean) =>
  api<{ status?: string }>(apiBaseUrl, '/api/computer/foreground', { method: 'POST', json: { run_id: runId, approve } });

export const pauseComputer = (apiBaseUrl: string, runId: string) =>
  api<{ status?: string }>(apiBaseUrl, '/api/computer/pause', { method: 'POST', json: { run_id: runId } });

export const getComputerStatus = (apiBaseUrl: string) => api<ComputerStatus>(apiBaseUrl, '/api/computer/status');

export const getComputerSteps = (apiBaseUrl: string, runId: string) =>
  api<{ steps?: ComputerStep[] }>(apiBaseUrl, `/api/computer/runs/${encodeURIComponent(runId)}/steps`);

// ---------- 浏览器代理 ----------

export type BrowserHandoffResolution = 'open_panel' | 'done' | 'give_up';

export type BrowserControlMode = 'standalone' | 'copied-profile' | 'cdp' | 'extension';

/** GET/POST /api/browser/settings：接管方式、CDP 地址与代理。 */
export interface BrowserSettings {
  mode?: BrowserControlMode;
  cdp_url?: string;
  proxy?: string;
}

/** POST /api/browser/recordings 的返回：一次录制会话。 */
export interface BrowserRecording {
  recording_id: string;
  status?: string;
  step_count?: number;
}

/** POST /api/browser/recordings/{id}/to-skill 的返回：dry_run 时带 skill_md 预览，保存后带 skill_id / path。 */
export interface RecordingSkill {
  skill_id?: string;
  name?: string;
  path?: string;
  skill_md?: string;
}

/** GET /api/browser/vault 的条目：只含句柄信息，永远不含密码明文。 */
export interface VaultEntry {
  id: string;
  label: string;
  username?: string;
  url?: string;
  created_at?: string;
}

/** POST /api/browser/vault 的新增请求：密码只在提交时出现一次。 */
export interface VaultNewEntry {
  label: string;
  username?: string;
  password: string;
  url?: string;
}

export const resolveBrowserHandoff = (apiBaseUrl: string, runId: string, resolution: BrowserHandoffResolution) =>
  api<{ status?: string }>(apiBaseUrl, '/api/browser/handoff', { method: 'POST', json: { run_id: runId, resolution } });

export const getBrowserSettings = (apiBaseUrl: string) => api<BrowserSettings>(apiBaseUrl, '/api/browser/settings');

export const saveBrowserSettings = (apiBaseUrl: string, settings: BrowserSettings) =>
  api<BrowserSettings>(apiBaseUrl, '/api/browser/settings', { method: 'POST', json: settings });

export const controlBrowserRecording = (apiBaseUrl: string, action: 'start' | 'stop', recordingId?: string) =>
  api<BrowserRecording>(apiBaseUrl, '/api/browser/recordings', { method: 'POST', json: { action, ...(recordingId ? { recording_id: recordingId } : {}) } });

/** 存为技能：先 dry_run=true 拿 SKILL.md 预览，确认后 dry_run=false 真正保存。 */
export const recordingToSkill = (apiBaseUrl: string, recordingId: string, body: { dry_run: boolean; name?: string }) =>
  api<RecordingSkill>(apiBaseUrl, `/api/browser/recordings/${encodeURIComponent(recordingId)}/to-skill`, { method: 'POST', json: body });

export const listVaultEntries = (apiBaseUrl: string) => api<VaultEntry[] | { entries?: VaultEntry[] }>(apiBaseUrl, '/api/browser/vault');

export const addVaultEntry = (apiBaseUrl: string, entry: VaultNewEntry) =>
  api<VaultEntry>(apiBaseUrl, '/api/browser/vault', { method: 'POST', json: entry });

export const deleteVaultEntry = (apiBaseUrl: string, id: string) =>
  api<void>(apiBaseUrl, `/api/browser/vault/${encodeURIComponent(id)}`, { method: 'DELETE' });

/** 后端可能返回裸数组或 { entries: [...] }，两种都接。 */
export const normalizeEntries = (value: VaultEntry[] | { entries?: VaultEntry[] } | undefined): VaultEntry[] =>
  Array.isArray(value) ? value : value?.entries ?? [];
