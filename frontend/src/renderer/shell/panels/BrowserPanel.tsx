import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { ArrowLeft, ArrowRight, BoxSelect, Code2, Crosshair, FileText, Plus, ScrollText, ExternalLink, Globe, Monitor, RotateCw, Smartphone, Tablet, X } from 'lucide-react';
import type { AgentEvent } from '../../../types/runtime';
import { backend } from '../../store/useAtlasStore';
import BrowserRecorderPanel, { type BrowserStepView } from '../../components/x2/BrowserRecorderPanel';
import { api } from '../../services/api';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';
import { BROWSER_FAILURE_GUIDE, classifyBrowserFailure, type BrowserFailureKind } from './browserErrors';

/** Must match BROWSER_PARTITION in the Electron main process: pages here never share the app's session. */
const PARTITION = 'persist:atlas-browser';
const USER_RECORDER_INSTALL = `(() => {
  if (window.__atlasUserRecorder) return true;
  const key = '__atlas_browser_steps';
  const selector = (el) => {
    const parts = [];
    for (; el && el.nodeType === 1 && parts.length < 6; el = el.parentElement) {
      if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
      let part = el.tagName.toLowerCase();
      const label = el.getAttribute('aria-label') || el.getAttribute('name');
      if (label) part += '[aria-label="' + CSS.escape(label.slice(0, 80)) + '"]';
      else { const siblings = el.parentElement ? [...el.parentElement.children].filter((node) => node.tagName === el.tagName) : []; if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')'; }
      parts.unshift(part);
    }
    return parts.join(' > ');
  };
  const target = (el) => String(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.textContent || el.tagName).trim().replace(/\\s+/g, ' ').slice(0, 220);
  const push = (item) => { try { const old = JSON.parse(localStorage.getItem(key) || '[]'); old.push({ ...item, url: location.href }); localStorage.setItem(key, JSON.stringify(old.slice(-40))); } catch {} };
  const click = (event) => { const el = event.target?.closest?.('button,a,[role=button],input[type=button],input[type=submit]'); if (el) push({ action: 'click', selector: selector(el), target: target(el) }); };
  const input = (event) => { const el = event.target; if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement)) return;
    const password = el instanceof HTMLInputElement && el.type.toLowerCase() === 'password';
    push({ action: 'type', selector: selector(el), target: target(el), password_field: password, value: password ? undefined : el.value }); };
  document.addEventListener('click', click, true); document.addEventListener('change', input, true);
  window.__atlasUserRecorder = { click, input }; return true;
})()`;
const USER_RECORDER_READ = `(() => { try { const key = '__atlas_browser_steps'; const rows = JSON.parse(localStorage.getItem(key) || '[]'); localStorage.removeItem(key); return Array.isArray(rows) ? rows : []; } catch { return []; } })()`;
const USER_RECORDER_REMOVE = `(() => { const rec = window.__atlasUserRecorder; if (!rec) return; document.removeEventListener('click', rec.click, true); document.removeEventListener('change', rec.input, true); delete window.__atlasUserRecorder; localStorage.removeItem('__atlas_browser_steps'); })()`;

/** Viewport presets for checking a page at other sizes; the panel scales them down to fit. */
const DEVICES = {
  fit: { label: '自适应', width: 0, height: 0, icon: Globe },
  phone: { label: '手机', width: 390, height: 844, icon: Smartphone },
  tablet: { label: '平板', width: 820, height: 1180, icon: Tablet },
  desktop: { label: '桌面', width: 1440, height: 900, icon: Monitor },
} as const;
type Device = keyof typeof DEVICES;

/** What the user picked on a page, ready to hand to the Agent. */
export interface PickedElement {
  /** A single element, or a dragged rectangle and the text inside it. */
  kind: 'element' | 'region';
  url: string;
  selector: string;
  tag: string;
  text: string;
  html: string;
  screenshot?: string;
}

interface WebviewElement extends HTMLElement {
  src: string;
  canGoBack(): boolean;
  canGoForward(): boolean;
  goBack(): void;
  goForward(): void;
  reload(): void;
  stop(): void;
  getURL(): string;
  loadURL(url: string): Promise<void>;
  openDevTools(): void;
  getZoomFactor(): number;
  getWebContentsId(): number;
  setZoomFactor(factor: number): void;
  executeJavaScript<T>(code: string): Promise<T>;
  capturePage(): Promise<{ toDataURL(): string }>;
  findInPage(text: string, options?: { forward?: boolean; findNext?: boolean; matchCase?: boolean }): number;
  stopFindInPage(action: 'clearSelection' | 'keepSelection' | 'activateSelection'): void;
}

interface BrowserTab {
  id: number;
  /** Set once when the tab first loads; changing it later would reload the embedded page. */
  initialUrl: string;
  /** Current committed page URL, independent from the webview's immutable initial `src`. */
  url: string;
  /** Address-bar text is stored per tab so an unfinished edit survives tab switches. */
  address: string;
  title: string;
  zoom: number;
}

function tabTitle(url: string): string {
  if (!url) return '新标签页';
  try { return new URL(url).host || url; } catch { return url; }
}

function sameWorkspace(left: string, right: string): boolean {
  const normalizeWorkspace = (value: string) => {
    const normalized = value.trim().replace(/\\/g, '/').replace(/\/+$/, '');
    return /^[a-z]:\//i.test(normalized) ? normalized.toLowerCase() : normalized;
  };
  return normalizeWorkspace(left) === normalizeWorkspace(right);
}

// Runs inside the page: highlight what the pointer is over, resolve with the clicked element, Escape cancels.
const PICKER = `new Promise((resolve) => {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;border:2px solid #c8963e;background:rgba(200,150,62,.15);border-radius:3px;transition:all .05s';
  document.documentElement.appendChild(box);
  const path = (el) => {
    const parts = [];
    for (; el && el.nodeType === 1 && parts.length < 6; el = el.parentElement) {
      if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
      let part = el.tagName.toLowerCase();
      const cls = [...el.classList].slice(0, 2).map((c) => '.' + CSS.escape(c)).join('');
      const siblings = el.parentElement ? [...el.parentElement.children].filter((c) => c.tagName === el.tagName) : [];
      part += cls || (siblings.length > 1 ? ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')' : '');
      parts.unshift(part);
    }
    return parts.join(' > ');
  };
  const move = (e) => { const r = e.target.getBoundingClientRect(); Object.assign(box.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' }); };
  const done = (value) => { removeEventListener('mousemove', move, true); removeEventListener('click', click, true); removeEventListener('keydown', key, true); box.remove(); resolve(value); };
  const click = (e) => {
    e.preventDefault(); e.stopPropagation();
    const el = e.target, r = el.getBoundingClientRect();
    done({ selector: path(el), tag: el.tagName.toLowerCase(), text: (el.innerText || '').trim().slice(0, 300), html: el.outerHTML.slice(0, 1500),
      rect: { x: Math.max(0, r.left), y: Math.max(0, r.top), width: Math.max(1, r.width), height: Math.max(1, r.height) }, viewport: innerWidth });
  };
  const key = (e) => { if (e.key === 'Escape') { e.preventDefault(); done(null); } };
  addEventListener('mousemove', move, true); addEventListener('click', click, true); addEventListener('keydown', key, true);
})`;

interface Rect { x: number; y: number; width: number; height: number }

/**
 * Cut the picked element out of a full-page capture. The capture is in device pixels and the rect in CSS
 * pixels, so scale by how wide the capture is compared with the page's viewport; a little margin keeps context.
 */
async function cropElement(capture: string, rect: Rect, viewport: number): Promise<string> {
  const image = new Image();
  image.src = capture;
  await image.decode();
  const scale = image.naturalWidth / Math.max(1, viewport);
  const margin = 8;
  const x = Math.max(0, (rect.x - margin) * scale);
  const y = Math.max(0, (rect.y - margin) * scale);
  const width = Math.min(image.naturalWidth - x, (rect.width + margin * 2) * scale);
  const height = Math.min(image.naturalHeight - y, (rect.height + margin * 2) * scale);
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width));
  canvas.height = Math.max(1, Math.round(height));
  const context = canvas.getContext('2d');
  context?.drawImage(image, x, y, width, height, 0, 0, canvas.width, canvas.height);
  if (context) {
    context.strokeStyle = '#d59a32';
    context.lineWidth = Math.max(3, Math.round(scale * 3));
    context.strokeRect(context.lineWidth / 2, context.lineWidth / 2, canvas.width - context.lineWidth, canvas.height - context.lineWidth);
  }
  return canvas.toDataURL('image/png');
}

// Runs inside the page: drag a rectangle, resolve with it and the visible text it covers; Escape cancels.
const REGION = `new Promise((resolve) => {
  const layer = document.createElement('div');
  layer.style.cssText = 'position:fixed;inset:0;z-index:2147483647;cursor:crosshair;background:rgba(0,0,0,.04)';
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;border:2px dashed #c8963e;background:rgba(200,150,62,.12);pointer-events:none;display:none';
  layer.appendChild(box); document.documentElement.appendChild(layer);
  let start = null;
  const rect = (e) => ({ x: Math.min(start.x, e.clientX), y: Math.min(start.y, e.clientY), width: Math.abs(e.clientX - start.x), height: Math.abs(e.clientY - start.y) });
  const done = (value) => { layer.remove(); removeEventListener('keydown', key, true); resolve(value); };
  const key = (e) => { if (e.key === 'Escape') { e.preventDefault(); done(null); } };
  layer.addEventListener('mousedown', (e) => { e.preventDefault(); start = { x: e.clientX, y: e.clientY }; box.style.display = 'block'; Object.assign(box.style, { left: start.x + 'px', top: start.y + 'px', width: '0', height: '0' }); });
  layer.addEventListener('mousemove', (e) => { if (!start) return; const r = rect(e); Object.assign(box.style, { left: r.x + 'px', top: r.y + 'px', width: r.width + 'px', height: r.height + 'px' }); });
  layer.addEventListener('mouseup', (e) => {
    if (!start) return;
    const r = rect(e);
    if (r.width < 8 || r.height < 8) { start = null; box.style.display = 'none'; return; }
    layer.remove();
    const texts = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node && texts.join(' ').length < 600; node = walker.nextNode()) {
      const text = node.textContent.trim(); if (!text) continue;
      const range = document.createRange(); range.selectNodeContents(node); const b = range.getBoundingClientRect();
      if (b.right > r.x && b.left < r.x + r.width && b.bottom > r.y && b.top < r.y + r.height) texts.push(text);
    }
    done({ rect: r, text: texts.join(' ').slice(0, 600), viewport: innerWidth });
  });
  addEventListener('keydown', key, true);
})`;

const normalize = (value: string) => {
  const text = value.trim();
  if (!text) return '';
  if (/^(https?|file):/i.test(text)) return text;
  if (/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/i.test(text)) return `http://${text}`;
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/|$)/.test(text)) return `https://${text}`;
  return `https://www.bing.com/search?q=${encodeURIComponent(text)}`;
};

function localDocumentKind(file: File): 'html' | 'pdf' | 'image' | 'video' | null {
  if (/\.html?$/i.test(file.name)) return 'html';
  if (file.type === 'application/pdf' || /\.pdf$/i.test(file.name)) return 'pdf';
  if (file.type.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg|bmp|avif)$/i.test(file.name)) return 'image';
  if (file.type.startsWith('video/') || /\.(mp4|webm|ogv|ogg|mov|m4v)$/i.test(file.name)) return 'video';
  return null;
}

/**
 * A browser next to the conversation for checking what the Agent built.
 * Pages run in their own session with no access to Atlas; picking an element hands its details to the composer.
 */
export default function BrowserPanel({ url, onUrl, suggestions, onPick, onToast, onAsk, workspace, apiBaseUrl, runId, events }: {
  url: string;
  onUrl: (url: string) => void;
  /** Local servers the Agent mentioned, offered as one-click targets. */
  suggestions: string[];
  onPick: (picked: PickedElement) => void;
  onToast: (text: string) => void;
  /** Hand a request to Atlas, e.g. to summarise the open page. */
  onAsk?: (text: string) => void;
  /** Active conversation/worktree workspace; browser artifact events are accepted only for this root. */
  workspace?: string | null;
  /** X2 操作录制：后端地址；给了才显示底部的录制区。 */
  apiBaseUrl?: string;
  /** 活动任务的 runId / 事件流；缺省时录制面板自己从全局事件流取。 */
  runId?: string;
  events?: AgentEvent[];
}) {
  const [tabs, setTabs] = useState<BrowserTab[]>(() => [{ id: 0, initialUrl: url, url, address: url, title: tabTitle(url), zoom: 1 }]);
  const [activeTabId, setActiveTabId] = useState(0);
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? tabs[0];
  const [loadingTabs, setLoadingTabs] = useState<Set<number>>(() => new Set());
  const [loadErrors, setLoadErrors] = useState<Record<number, { code: number; description: string; kind: BrowserFailureKind }>>({});
  const [nav, setNav] = useState({ back: false, forward: false });
  const [picking, setPicking] = useState<'' | 'element' | 'region'>('');
  const [pendingPick, setPendingPick] = useState<PickedElement | null>(null);
  const [annotation, setAnnotation] = useState('');
  const [localFile, setLocalFile] = useState<File | null>(null);
  const [localFileUrl, setLocalFileUrl] = useState('');
  const [findOpen, setFindOpen] = useState(false);
  const [findText, setFindText] = useState('');
  const [findCount, setFindCount] = useState({ activeMatchOrdinal: 0, matches: 0 });
  const findInputRef = useRef<HTMLInputElement | null>(null);
  const localFileInput = useRef<HTMLInputElement | null>(null);
  const addressInputRef = useRef<HTMLInputElement | null>(null);
  const tabsRef = useRef(tabs);
  const activeTabIdRef = useRef(activeTabId);
  const onUrlRef = useRef(onUrl);
  const onToastRef = useRef(onToast);
  const lastReportedUrlRef = useRef(url);
  const lastPanelSyncRef = useRef({ runId: '', sequence: -1 });
  const lastBrowserArtifactRef = useRef({ runId: '', sequence: -1 });
  const nextTabIdRef = useRef(1);
  const viewRefs = useRef(new Map<number, WebviewElement>());
  const boundViewRefs = useRef(new Map<number, { view: WebviewElement; listeners: Array<[string, EventListener]> }>());
  const zoomGestureRef = useRef<(id: number, event: Event) => void>(() => undefined);
  const webviewRefCallbacks = useRef(new Map<number, (node: Element | null) => void>());
  const tabButtonRefs = useRef(new Map<number, HTMLButtonElement>());
  const tabButtonRefCallbacks = useRef(new Map<number, (node: HTMLButtonElement | null) => void>());
  tabsRef.current = tabs;
  activeTabIdRef.current = activeTabId;
  onUrlRef.current = onUrl;
  onToastRef.current = onToast;
  const reportUrlRef = useRef<(next: string) => void>(() => undefined);
  reportUrlRef.current = (next) => { lastReportedUrlRef.current = next; onUrlRef.current(next); };
  const bindWebviewRef = useRef<(id: number, node: Element | null) => void>(() => undefined);
  bindWebviewRef.current = (id, node) => {
    const existing = boundViewRefs.current.get(id);
    if (existing) {
      for (const [name, listener] of existing.listeners) existing.view.removeEventListener(name, listener);
      boundViewRefs.current.delete(id);
    }
    if (!node) { viewRefs.current.delete(id); return; }
    const view = node as WebviewElement;
    viewRefs.current.set(id, view);
    const sync = () => {
      const current = view.getURL();
      if (!current) return;
      setTabs((previous) => previous.map((tab) => tab.id === id ? { ...tab, url: current, address: current } : tab));
      if (activeTabIdRef.current === id) {
        setNav({ back: view.canGoBack(), forward: view.canGoForward() });
        reportUrlRef.current(current);
      }
    };
    const start = () => {
      setLoadingTabs((previous) => new Set(previous).add(id));
      setLoadErrors((previous) => { if (!previous[id]) return previous; const next = { ...previous }; delete next[id]; return next; });
    };
    const stop = () => {
      setLoadingTabs((previous) => { const next = new Set(previous); next.delete(id); return next; });
      const current = tabsRef.current.find((tab) => tab.id === id);
      if (current) view.setZoomFactor(current.zoom);
      sync();
    };
    const failed = (event: Event) => {
      const detail = event as Event & { errorCode?: number; errorDescription?: string; isMainFrame?: boolean };
      if (detail.isMainFrame && detail.errorCode !== -3) {
        const code = detail.errorCode ?? 0;
        const description = detail.errorDescription ?? `Chromium error ${code}`;
        setLoadErrors((previous) => ({ ...previous, [id]: { code, description, kind: classifyBrowserFailure(code, description) } }));
      }
    };
    const title = (event: Event) => {
      const detail = event as Event & { title?: string };
      if (detail.title) setTabs((previous) => previous.map((tab) => tab.id === id ? { ...tab, title: detail.title! } : tab));
    };
    const found = (event: Event) => {
      const result = (event as Event & { result?: { activeMatchOrdinal: number; matches: number } }).result;
      if (result && activeTabIdRef.current === id) setFindCount(result);
    };
    const zoomGesture = (event: Event) => zoomGestureRef.current(id, event);
    const listeners: Array<[string, EventListener]> = [
      ['did-start-loading', start], ['did-stop-loading', stop], ['did-navigate', sync],
      ['did-navigate-in-page', sync], ['did-fail-load', failed], ['page-title-updated', title], ['found-in-page', found],
      ['keydown', zoomGesture],
    ];
    for (const [name, listener] of listeners) view.addEventListener(name, listener);
    boundViewRefs.current.set(id, { view, listeners });
  };
  const getWebviewRef = (id: number) => {
    let callback = webviewRefCallbacks.current.get(id);
    if (!callback) {
      callback = (node) => bindWebviewRef.current(id, node);
      webviewRefCallbacks.current.set(id, callback);
    }
    return callback;
  };
  const getTabButtonRef = (id: number) => {
    let callback = tabButtonRefCallbacks.current.get(id);
    if (!callback) {
      callback = (node) => {
        if (node) tabButtonRefs.current.set(id, node);
        else tabButtonRefs.current.delete(id);
      };
      tabButtonRefCallbacks.current.set(id, callback);
    }
    return callback;
  };
  const [device, setDevice] = useState<Device>('fit');
  const [recorderOpen, setRecorderOpen] = useState(false);
  const [userRecordingId, setUserRecordingId] = useState<string | null>(null);
  const [recordedUserSteps, setRecordedUserSteps] = useState<BrowserStepView[]>([]);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [stage, setStage] = useState({ width: 0, height: 0 });
  const [zoomBannerTab, setZoomBannerTab] = useState<number | null>(null);
  const zoomBannerTimerRef = useRef<number | null>(null);
  useEffect(() => {
    const node = stageRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setStage({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const desktop = typeof window !== 'undefined' && Boolean(window.atlasDesktop);

  const closeFind = () => {
    viewRefs.current.get(activeTabIdRef.current)?.stopFindInPage('clearSelection');
    setFindOpen(false);
    setFindText('');
    setFindCount({ activeMatchOrdinal: 0, matches: 0 });
  };
  const searchPage = (query: string, forward = true, findNext = false) => {
    setFindText(query);
    const view = viewRefs.current.get(activeTabIdRef.current);
    if (!query.trim() || !view) {
      view?.stopFindInPage('clearSelection');
      setFindCount({ activeMatchOrdinal: 0, matches: 0 });
      return;
    }
    view.findInPage(query, { forward, findNext, matchCase: false });
  };
  useEffect(() => {
    const open = () => { setFindOpen(true); window.requestAnimationFrame(() => { findInputRef.current?.focus(); findInputRef.current?.select(); }); };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') { event.preventDefault(); open(); }
      else if (event.key === 'Escape' && findOpen) { event.preventDefault(); closeFind(); }
    };
    const onFind = () => open();
    const unsubscribe = window.atlasDesktop?.onBrowserFind?.(onFind);
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('atlas:browser-find', onFind);
    return () => { unsubscribe?.(); document.removeEventListener('keydown', onKey, true); window.removeEventListener('atlas:browser-find', onFind); };
  }, [findOpen]);

  useEffect(() => {
    if (!userRecordingId || !apiBaseUrl) {
      for (const view of viewRefs.current.values()) void view.executeJavaScript(USER_RECORDER_REMOVE).catch(() => undefined);
      return;
    }
    let stale = false;
    let busy = false;
    let lastUrl = '';
    const record = async (step: { action: string; url?: string; selector?: string; target?: string; value?: string; password_field?: boolean }) => {
      if (stale) return;
      try {
        const result = await api<{ step: { index: number; action: string; description?: string; params?: Record<string, unknown>; site?: string } }>(
          apiBaseUrl, `/api/browser/recordings/${encodeURIComponent(userRecordingId)}/steps`, { method: 'POST', json: step },
        );
        const saved = result.step;
        setRecordedUserSteps((items) => [...items, {
          id: `user-recording-${saved.index}-${Date.now()}`, index: saved.index + 1,
          action: saved.action, target: String(saved.params?.target ?? saved.description ?? ''), url: String(saved.site ?? step.url ?? ''),
        }]);
      } catch { /* an already stopped recording no longer accepts page events */ }
    };
    const poll = async () => {
      if (stale || busy) return;
      const view = viewRefs.current.get(activeTabIdRef.current);
      if (!view) return;
      busy = true;
      try {
        const url = view.getURL();
        if (url && url !== lastUrl) {
          lastUrl = url;
          await record({ action: 'navigate', url });
          window.setTimeout(() => { void record({ action: 'wait', url, target: '页面加载完成' }); }, 700);
        }
        await view.executeJavaScript(USER_RECORDER_INSTALL);
        const rows = await view.executeJavaScript<Array<{ action: string; url?: string; selector?: string; target?: string; value?: string; password_field?: boolean }>>(USER_RECORDER_READ);
        if (Array.isArray(rows)) for (const row of rows) await record(row);
      } catch { /* Some browser pages block script access; continue recording other pages. */ }
      finally { busy = false; }
    };
    const timer = window.setInterval(() => { void poll(); }, 800);
    void poll();
    return () => { stale = true; window.clearInterval(timer); };
  }, [apiBaseUrl, userRecordingId, activeTabId]);

  useEffect(() => {
    if (!localFile) { setLocalFileUrl(''); return; }
    const objectUrl = URL.createObjectURL(localFile);
    setLocalFileUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [localFile]);

  const navigateTabRef = useRef<(id: number, raw: string, notify?: boolean) => void>(() => undefined);
  navigateTabRef.current = (id, raw, notify = true) => {
    const next = normalize(raw);
    if (!next) return;
    const tab = tabsRef.current.find((item) => item.id === id);
    if (!tab) return;
    setLocalFile(null);
    setPendingPick(null);
    if (findOpen) closeFind();
    setTabs((previous) => previous.map((item) => item.id === id ? {
      ...item, url: next, address: next, initialUrl: item.initialUrl || next,
      title: tabTitle(next),
    } : item));
    if (tab.initialUrl) void viewRefs.current.get(id)?.loadURL(next).catch(() => undefined);
    if (notify && activeTabIdRef.current === id) reportUrlRef.current(next);
  };
  useEffect(() => {
    if (url === lastReportedUrlRef.current) return;
    lastReportedUrlRef.current = url;
    if (url) navigateTabRef.current(activeTabIdRef.current, url, false);
  }, [url]);
  useEffect(() => {
    const eventRunId = runId ?? '';
    if (lastPanelSyncRef.current.runId !== eventRunId) lastPanelSyncRef.current = { runId: eventRunId, sequence: -1 };
    const syncs = events
      ?.filter((event) => event.type === 'browser.panel.sync' && (!runId || event.runId === runId)
        && event.sequence > lastPanelSyncRef.current.sequence)
      .sort((left, right) => left.sequence - right.sequence) ?? [];
    if (!syncs.length) return;

    const latest = syncs[syncs.length - 1];
    for (const event of syncs) lastPanelSyncRef.current.sequence = event.sequence;
    const nextUrl = typeof latest.data.url === 'string' ? latest.data.url : '';
    if (!nextUrl) return;

    const activeId = activeTabIdRef.current;
    const tab = tabsRef.current.find((item) => item.id === activeId);
    const title = typeof latest.data.title === 'string' && latest.data.title ? latest.data.title : tabTitle(nextUrl);
    setLocalFile(null);
    setPendingPick(null);
    if (findOpen) closeFind();
    setTabs((previous) => previous.map((item) => item.id === activeId
      ? { ...item, initialUrl: item.initialUrl || nextUrl, url: nextUrl, address: nextUrl, title }
      : item));
    if (tab?.url !== nextUrl) void viewRefs.current.get(activeId)?.loadURL(nextUrl).catch(() => undefined);
    setNav({ back: false, forward: false });
    reportUrlRef.current(nextUrl);
  }, [events, runId]);
  useEffect(() => {
    if (!runId || !workspace) return;
    if (lastBrowserArtifactRef.current.runId !== runId) lastBrowserArtifactRef.current = { runId, sequence: -1 };
    const artifacts = events
      ?.filter((event) => event.type === 'browser.artifact' && event.runId === runId
        && event.sequence > lastBrowserArtifactRef.current.sequence)
      .sort((left, right) => left.sequence - right.sequence) ?? [];
    if (!artifacts.length) return;

    for (const event of artifacts) {
      lastBrowserArtifactRef.current.sequence = event.sequence;
      const eventWorkspace = typeof event.data.workspace === 'string' ? event.data.workspace : '';
      const artifactPath = typeof event.data.artifact_path === 'string' ? event.data.artifact_path : '';
      if (!eventWorkspace || !sameWorkspace(eventWorkspace, workspace)
        || !/^artifacts\/browser\/[a-f0-9]{32}\.png$/i.test(artifactPath)) continue;

      const artifactUrl = backend.rawFileUrl(workspace, artifactPath);
      const activeId = activeTabIdRef.current;
      navigateTabRef.current(activeId, artifactUrl);
      setTabs((previous) => previous.map((tab) => tab.id === activeId
        ? { ...tab, title: `截图 · ${artifactPath.slice(18)}` }
        : tab));
    }
  }, [events, runId, workspace]);
  useEffect(() => {
    if (activeTab) {
      const view = viewRefs.current.get(activeTab.id);
      setNav(view ? { back: view.canGoBack(), forward: view.canGoForward() } : { back: false, forward: false });
    }
  }, [activeTabId, activeTab?.id]);

  const go = (event?: FormEvent) => {
    event?.preventDefault();
    if (activeTab) navigateTabRef.current(activeTab.id, activeTab.address);
  };
  const activateTab = (id: number) => {
    const tab = tabsRef.current.find((item) => item.id === id);
    if (!tab) return;
    activeTabIdRef.current = id;
    setActiveTabId(id);
    setPendingPick(null);
    setAnnotation('');
    const view = viewRefs.current.get(id);
    setNav(view ? { back: view.canGoBack(), forward: view.canGoForward() } : { back: false, forward: false });
    reportUrlRef.current(tab.url);
  };
  const addTab = () => {
    const id = nextTabIdRef.current++;
    const tab: BrowserTab = { id, initialUrl: '', url: '', address: '', title: '新标签页', zoom: 1 };
    const next = [...tabsRef.current, tab];
    tabsRef.current = next;
    activeTabIdRef.current = id;
    setTabs(next);
    setActiveTabId(id);
    setNav({ back: false, forward: false });
    setLocalFile(null);
    setPendingPick(null);
    setAnnotation('');
    reportUrlRef.current('');
    window.requestAnimationFrame(() => tabButtonRefs.current.get(id)?.focus());
  };
  const closeTab = (id: number) => {
    const current = tabsRef.current;
    const index = current.findIndex((tab) => tab.id === id);
    if (index < 0) return;
    viewRefs.current.get(id)?.setZoomFactor(1);
    if (zoomBannerTimerRef.current !== null) window.clearTimeout(zoomBannerTimerRef.current);
    setZoomBannerTab((currentId) => currentId === id ? null : currentId);
    const closingActive = id === activeTabIdRef.current;
    let next = current.filter((tab) => tab.id !== id);
    if (!next.length) {
      const blankId = nextTabIdRef.current++;
      next = [{ id: blankId, initialUrl: '', url: '', address: '', title: '新标签页', zoom: 1 }];
    }
    tabsRef.current = next;
    setTabs(next);
    viewRefs.current.delete(id);
    webviewRefCallbacks.current.delete(id);
    tabButtonRefCallbacks.current.delete(id);
    setLoadingTabs((previous) => { const loading = new Set(previous); loading.delete(id); return loading; });
    const target = next[Math.min(index, next.length - 1)];
    if (closingActive) {
      activeTabIdRef.current = target.id;
      setActiveTabId(target.id);
      setPendingPick(null);
      setAnnotation('');
      const view = viewRefs.current.get(target.id);
      setNav(view ? { back: view.canGoBack(), forward: view.canGoForward() } : { back: false, forward: false });
      reportUrlRef.current(target.url);
      window.requestAnimationFrame(() => tabButtonRefs.current.get(target.id)?.focus());
    }
  };
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 't') {
      event.preventDefault(); addTab(); return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'w') {
      event.preventDefault(); closeTab(activeTabIdRef.current); return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'l') {
      event.preventDefault(); addressInputRef.current?.focus(); addressInputRef.current?.select(); return;
    }
    const destination = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
    if (destination >= 0 && tabs[destination]) {
      event.preventDefault();
      const next = tabs[destination];
      activateTab(next.id);
      tabButtonRefs.current.get(next.id)?.focus();
    }
  };
  const pick = async (kind: 'element' | 'region') => {
    const view = viewRefs.current.get(activeTabIdRef.current);
    if (!view || picking) return;
    setPicking(kind);
    try {
      const result = await view.executeJavaScript<{ selector?: string; tag?: string; text: string; html?: string; rect: Rect; viewport: number } | null>(kind === 'element' ? PICKER : REGION);
      if (!result) return;
      let screenshot: string | undefined;
      try { screenshot = await cropElement((await view.capturePage()).toDataURL(), result.rect, result.viewport); } catch { screenshot = undefined; }
      setPendingPick({ kind, url: view.getURL(), selector: result.selector ?? '', tag: result.tag ?? '', text: result.text, html: result.html ?? '', screenshot });
      setAnnotation('');
    } catch {
      onToast(kind === 'element' ? '这个页面不允许点选元素' : '这个页面不允许框选');
    } finally { setPicking(''); }
  };

  if (!desktop) return <Empty title="在桌面版里使用" body="浏览器面板需要 Atlas 桌面应用，网页版里不可用。" icon={<Globe size={22} />} />;

  const size = device === 'fit' ? null : DEVICES[device];
  const scale = size && stage.width && stage.height ? Math.min(1, stage.width / size.width, stage.height / size.height) : 1;
  const button = 'grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg disabled:opacity-35 disabled:hover:bg-transparent';
  const finishPick = () => {
    if (!pendingPick) return;
    const note = annotation.trim();
    onPick(note ? { ...pendingPick, text: `${pendingPick.text}${pendingPick.text ? '\n\n' : ''}用户批注：${note}` } : pendingPick);
    setPendingPick(null);
    setAnnotation('');
  };
  const localKind = localFile ? localDocumentKind(localFile) : null;
  const activeView = activeTab ? viewRefs.current.get(activeTab.id) : undefined;
  const activeLoadError = activeTab ? loadErrors[activeTab.id] : undefined;
  const loading = loadingTabs.has(activeTabId);
  useEffect(() => {
    const view = viewRefs.current.get(activeTabId);
    if (view && activeTab) view.setZoomFactor(activeTab.zoom);
  }, [activeTabId, activeTab?.zoom]);
  const updateZoom = (id: number, next: number) => {
    const factor = Math.max(0.5, Math.min(2, Math.round(next * 100) / 100));
    setTabs((previous) => previous.map((tab) => tab.id === id ? { ...tab, zoom: factor } : tab));
    tabsRef.current = tabsRef.current.map((tab) => tab.id === id ? { ...tab, zoom: factor } : tab);
    viewRefs.current.get(id)?.setZoomFactor(factor);
    setZoomBannerTab(id);
    if (zoomBannerTimerRef.current !== null) window.clearTimeout(zoomBannerTimerRef.current);
    zoomBannerTimerRef.current = window.setTimeout(() => setZoomBannerTab((current) => current === id ? null : current), 2200);
  };
  useEffect(() => {
    const unsubscribe = window.atlasDesktop?.onBrowserZoom?.(({ webContentsId, action, factor: actualFactor }) => {
      const entry = [...viewRefs.current.entries()].find(([, view]) => view.getWebContentsId() === webContentsId);
      if (!entry) return;
      const current = tabsRef.current.find((tab) => tab.id === entry[0])?.zoom ?? 1;
      const factor = action === 'sync' ? Number(actualFactor) : action === 'in' ? current + 0.1 : action === 'out' ? current - 0.1 : 1;
      updateZoom(entry[0], Number.isFinite(factor) ? factor : current);
    });
    return () => unsubscribe?.();
  }, [activeTabId, activeTab?.zoom]);
  zoomGestureRef.current = (id, event) => {
    if (event.defaultPrevented) return;
    if (event instanceof WheelEvent && event.ctrlKey) {
      event.preventDefault();
      const current = tabsRef.current.find((tab) => tab.id === id)?.zoom ?? 1;
      updateZoom(id, current + (event.deltaY < 0 ? 0.1 : -0.1));
      return;
    }
    if (!(event instanceof KeyboardEvent) || !(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    const current = tabsRef.current.find((tab) => tab.id === id)?.zoom ?? 1;
    if (key === '+' || key === '=' || key === 'add') updateZoom(id, current + 0.1);
    else if (key === '-' || key === '_' || key === 'subtract') updateZoom(id, current - 0.1);
    else if (key === '0') updateZoom(id, 1);
    else return;
    event.preventDefault();
  };
  useEffect(() => {
    const view = viewRefs.current.get(activeTabId);
    if (view && activeTab) view.setZoomFactor(activeTab.zoom);
  }, [activeTabId, activeTab?.zoom]);
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || !activeTab) return;
      const key = event.key.toLowerCase();
      if (key === 'l') {
        event.preventDefault(); event.stopPropagation();
        addressInputRef.current?.focus(); addressInputRef.current?.select(); return;
      }
      if (key === '+' || key === '=' || key === 'add') {
        event.preventDefault(); updateZoom(activeTabIdRef.current, (tabsRef.current.find((tab) => tab.id === activeTabIdRef.current)?.zoom ?? 1) + 0.1);
      } else if (key === '-' || key === '_' || key === 'subtract') {
        event.preventDefault(); updateZoom(activeTabIdRef.current, (tabsRef.current.find((tab) => tab.id === activeTabIdRef.current)?.zoom ?? 1) - 0.1);
      } else if (key === '0') {
        event.preventDefault(); updateZoom(activeTabIdRef.current, 1);
      }
    };
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey || !activeTab) return;
      if (event.target instanceof Element && event.target.closest('webview')) return;
      event.preventDefault();
      const current = tabsRef.current.find((tab) => tab.id === activeTabIdRef.current)?.zoom ?? 1;
      updateZoom(activeTabIdRef.current, current + (event.deltaY < 0 ? 0.1 : -0.1));
    };
    document.addEventListener('keydown', onKey, true);
    const stage = stageRef.current;
    stage?.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      document.removeEventListener('keydown', onKey, true);
      stage?.removeEventListener('wheel', onWheel);
      if (zoomBannerTimerRef.current !== null) window.clearTimeout(zoomBannerTimerRef.current);
    };
  }, [activeTabId, activeTab?.id]);
  useEffect(() => {
    const view = viewRefs.current.get(activeTabId);
    let contentsId: number | null = null;
    try { contentsId = view?.getWebContentsId() ?? null; } catch { contentsId = null; }
    window.atlasDesktop?.setBrowserAddressShortcutWebContents?.(contentsId);
    const unsubscribe = window.atlasDesktop?.onBrowserAddressShortcut?.(() => {
      addressInputRef.current?.focus(); addressInputRef.current?.select();
    });
    return () => { unsubscribe?.(); window.atlasDesktop?.setBrowserAddressShortcutWebContents?.(null); };
  }, [activeTabId, activeTab?.id]);
  return <div className="flex h-full min-h-0 flex-col gap-2">
    <div className="flex min-w-0 items-center gap-1 border-b border-line" aria-label="浏览器标签">
      <div role="tablist" aria-label="浏览器标签页" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto py-1">
        {tabs.map((tab, index) => {
          const selected = tab.id === activeTabId;
          return <div key={tab.id} role="presentation" className={cn('flex h-7 max-w-52 shrink-0 items-center rounded-lg', selected ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover')}>
            <button ref={getTabButtonRef(tab.id)} type="button" role="tab" id={`browser-tab-${tab.id}`} aria-selected={selected} aria-controls="browser-tabpanel" tabIndex={selected ? 0 : -1}
              aria-label={`${tab.title}${tab.url ? `，${tab.url}` : ''}`} title={tab.url || tab.title} onClick={() => activateTab(tab.id)} onKeyDown={(event) => onTabKeyDown(event, index)}
              className="h-full min-w-0 truncate rounded-l-lg px-2 text-left text-[11.5px] outline-none focus-visible:ring-2 focus-visible:ring-brand">
              {loadingTabs.has(tab.id) && <span aria-label="正在加载" className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-brand align-middle" />}{tab.title}
            </button>
            <button type="button" aria-label={`关闭标签：${tab.title}`} title="关闭标签" onClick={() => closeTab(tab.id)} onKeyDown={(event) => onTabKeyDown(event, index)}
              className="grid size-6 shrink-0 place-items-center rounded-r-lg text-fg-3 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"><X size={11} /></button>
          </div>;
        })}
      </div>
      <button type="button" aria-label="新建浏览器标签" title="新建标签（Ctrl/⌘+T）" onClick={addTab} onKeyDown={(event) => onTabKeyDown(event, tabs.length - 1)}
        className="grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"><Plus size={14} /></button>
    </div>
    <form onSubmit={go} className="flex items-center gap-1">
      <button type="button" aria-label="后退" disabled={!nav.back || Boolean(localFile)} onClick={() => activeView?.goBack()} className={button}><ArrowLeft size={15} /></button>
      <button type="button" aria-label="前进" disabled={!nav.forward || Boolean(localFile)} onClick={() => activeView?.goForward()} className={button}><ArrowRight size={15} /></button>
      <button type="button" aria-label={loading ? '停止加载' : '刷新'} disabled={!activeTab?.url || Boolean(localFile)} onClick={() => loading ? activeView?.stop() : activeView?.reload()} className={button}>{loading ? <X size={15} /> : <RotateCw size={14} />}</button>
      <input ref={addressInputRef} aria-keyshortcuts="Control+L Meta+L" title="聚焦并全选地址（Ctrl+L / ⌘+L；浏览器面板内覆盖页面快捷键）" value={activeTab?.address ?? ''} onChange={(event) => {
        const value = event.target.value;
        if (activeTab) setTabs((previous) => previous.map((tab) => tab.id === activeTab.id ? { ...tab, address: value } : tab));
      }} onFocus={(event) => event.target.select()} placeholder="输入网址、localhost:端口，或搜索" aria-label="地址"
        className="h-8 min-w-0 flex-1 rounded-[9px] bg-sunken px-3 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      <input ref={localFileInput} type="file" accept=".html,.htm,.pdf,image/*,video/*" className="hidden" aria-label="选择本地 HTML、PDF、图片或视频" onChange={(event) => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = '';
        if (!file) return;
        if (!localDocumentKind(file)) {
          onToast('请选择 HTML、PDF、图片或视频文件'); return;
        }
        setLocalFile(file);
      }} />
      <button type="button" aria-label="预览本地文档" title="预览本地 HTML、PDF、图片或视频" onClick={() => localFileInput.current?.click()} className={button}><FileText size={15} /></button>
      <button type="button" aria-label="点选页面元素发给 Atlas" title="点选页面元素并添加批注（Esc 取消）" disabled={!activeTab?.url || Boolean(picking) || Boolean(localFile)} onClick={() => void pick('element')}
        className={cn(button, picking === 'element' && '!bg-brand-soft !text-fg')}><Crosshair size={15} /></button>
      <button type="button" aria-label="框选页面区域发给 Atlas" title="框选一块区域并添加批注（Esc 取消）" disabled={!activeTab?.url || Boolean(picking) || Boolean(localFile)} onClick={() => void pick('region')}
        className={cn(button, picking === 'region' && '!bg-brand-soft !text-fg')}><BoxSelect size={15} /></button>
      {onAsk && <button type="button" aria-label="让 Atlas 总结这页" title="让 Atlas 读这页正文（视频读字幕）并总结要点" disabled={!activeTab?.url || Boolean(localFile) || /^(about|file|data):/i.test(activeTab?.url ?? '')}
        onClick={() => {
          const current = activeView?.getURL() || activeTab?.url || '';
          const local = /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(current);
          onAsk(`用 web_extract 读取这个${/youtube\.com|youtu\.be|bilibili\.com/i.test(current) ? '视频的字幕' : '网页的正文'}${local ? '（是我本机的开发页面，allow_local 设为 true）' : ''}，然后用中文总结要点，最后列出值得注意的细节：
${current}`);
        }} className={button}><ScrollText size={15} /></button>}
      <button type="button" aria-label="开发者工具" disabled={!activeTab?.url || Boolean(localFile)} onClick={() => activeView?.openDevTools()} className={button}><Code2 size={15} /></button>
    </form>
    {findOpen && <div className="flex items-center gap-1 rounded-lg border border-line bg-surface px-2 py-1" role="search" aria-label="页内查找">
      <input ref={findInputRef} value={findText} onChange={(event) => searchPage(event.target.value)} onKeyDown={(event) => {
        if (event.key === 'Enter') { event.preventDefault(); searchPage(findText, !event.shiftKey, true); }
        if (event.key === 'Escape') { event.preventDefault(); closeFind(); }
      }} placeholder="查找当前页面" aria-label="查找文本" className="h-7 min-w-0 flex-1 bg-transparent text-[12px] outline-none" />
      <span className="min-w-12 text-center text-[11px] text-fg-3" aria-live="polite">{findText ? `${findCount.matches ? findCount.activeMatchOrdinal : 0}/${findCount.matches}` : '0/0'}</span>
      <button type="button" aria-label="上一个匹配" title="上一个匹配" disabled={!findCount.matches} onClick={() => searchPage(findText, false, true)} className={button}><ArrowLeft size={14} /></button>
      <button type="button" aria-label="下一个匹配" title="下一个匹配" disabled={!findCount.matches} onClick={() => searchPage(findText, true, true)} className={button}><ArrowRight size={14} /></button>
      <button type="button" aria-label="关闭查找" title="关闭（Esc）" onClick={closeFind} className={button}><X size={14} /></button>
    </div>}
    {activeTab?.url && !localFile && <div className="flex items-center gap-0.5 text-[12px]" role="group" aria-label="预览尺寸">
      {(Object.keys(DEVICES) as Device[]).map((key) => {
        const Icon = DEVICES[key].icon;
        return <button key={key} type="button" onClick={() => setDevice(key)} aria-pressed={device === key}
          className={cn('inline-flex h-6 items-center gap-1 rounded-md px-2', device === key ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}>
          <Icon size={12} />{DEVICES[key].label}</button>;
      })}
      {size && <span className="ml-auto tabular-nums text-fg-3">{size.width} × {size.height}{scale < 1 ? ` · ${Math.round(scale * 100)}%` : ''}</span>}
    </div>}
    {localFile && localFileUrl
      ? <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white shadow-[inset_0_0_0_1px_var(--line)]" aria-label={`本地文档预览：${localFile.name}`}>
        <div className="flex h-8 shrink-0 items-center gap-2 border-b border-line px-3 text-[12px] text-fg-2">
          <span className="min-w-0 flex-1 truncate">本地预览 · {localFile.name}</span>
          <button type="button" aria-label="关闭本地文档预览" onClick={() => setLocalFile(null)} className="grid size-6 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><X size={13} /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {localKind === 'image' && <img src={localFileUrl} alt={localFile.name} className="mx-auto max-h-full max-w-full object-contain" />}
          {localKind === 'video' && <video src={localFileUrl} controls className="h-full w-full" aria-label={localFile.name} />}
          {localKind === 'pdf' && <iframe src={localFileUrl} title={`PDF 预览：${localFile.name}`} className="h-full min-h-[360px] w-full border-0" />}
          {localKind === 'html' && <iframe src={localFileUrl} title={`HTML 预览：${localFile.name}`} sandbox="allow-scripts" className="h-full min-h-[360px] w-full border-0" />}
        </div>
      </section>
      : null}
    <div ref={stageRef} role="tabpanel" id="browser-tabpanel" aria-labelledby={`browser-tab-${activeTabId}`} tabIndex={0} className={cn('relative flex min-h-0 flex-1 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand', localFile && 'hidden', size && 'items-start justify-center overflow-hidden')}>
      {zoomBannerTab === activeTabId && activeTab?.initialUrl && <div role="group" aria-label="网页缩放" className="absolute right-3 top-3 z-40 flex items-center gap-1 rounded-xl border border-line bg-panel/95 p-1.5 text-fg shadow-xl backdrop-blur">
        <button type="button" aria-label="缩小网页" title="缩小网页（Ctrl 加减号）" onClick={() => updateZoom(activeTabId, activeTab.zoom - 0.1)} className="grid size-7 place-items-center rounded-lg text-fg-2 hover:bg-hover"><span aria-hidden="true">−</span></button>
        <span className="min-w-12 text-center font-mono text-[11px] tabular-nums" aria-live="polite">{Math.round(activeTab.zoom * 100)}%</span>
        <button type="button" aria-label="放大网页" title="放大网页（Ctrl 加加号）" onClick={() => updateZoom(activeTabId, activeTab.zoom + 0.1)} className="grid size-7 place-items-center rounded-lg text-fg-2 hover:bg-hover"><span aria-hidden="true">+</span></button>
        <span aria-hidden="true" className="mx-0.5 h-5 w-px bg-line" />
        <button type="button" aria-label="重置网页缩放" title="重置网页缩放（Ctrl+0）" onClick={() => updateZoom(activeTabId, 1)} className="rounded-lg px-2 py-1 text-[10.5px] text-fg-2 hover:bg-hover">重置</button>
      </div>}
        {activeLoadError && <section role="alert" aria-label="浏览器加载失败指引" className="absolute inset-x-3 top-3 z-30 max-h-[75%] overflow-auto rounded-xl border border-danger/30 bg-panel p-4 shadow-xl">
          <div className="flex items-start gap-2"><span className="min-w-0 flex-1"><b className="text-[14px] text-danger">{BROWSER_FAILURE_GUIDE[activeLoadError.kind].title}</b><small className="mt-1 block break-all font-mono text-[11px] text-fg-3">{activeLoadError.description} · Chromium {activeLoadError.code}</small></span><button type="button" aria-label="关闭错误指引" onClick={() => setLoadErrors((previous) => { const next = { ...previous }; delete next[activeTabId]; return next; })} className="rounded px-2 text-fg-3 hover:bg-hover">×</button></div>
          <ul className="my-2 grid list-disc gap-1 pl-5 text-[12.5px] text-fg-2">{BROWSER_FAILURE_GUIDE[activeLoadError.kind].checks.map((check) => <li key={check}>{check}</li>)}</ul>
          <div className="flex flex-wrap gap-2"><button type="button" onClick={() => { setLoadErrors((previous) => { const next = { ...previous }; delete next[activeTabId]; return next; }); activeView?.reload(); }} className="rounded-lg bg-brand-soft px-3 py-1.5 text-[12px] text-fg">重试</button><button type="button" onClick={() => void window.atlasDesktop?.openExternal?.('ms-settings:network-proxy')} className="rounded-lg px-3 py-1.5 text-[12px] text-fg-2 hover:bg-hover">打开系统代理设置</button></div>
        </section>}
        {/* Other device sizes render at full size and are scaled to fit, so the page lays out as it would there. */}
        {tabs.filter((tab) => tab.initialUrl).map((tab) => {
          const selected = tab.id === activeTabId;
          return <div key={tab.id} aria-hidden={!selected} className={cn('absolute inset-0 min-h-0 flex', selected ? 'visible' : 'invisible pointer-events-none', size && 'items-start justify-center')}>
            <div style={size ? { width: size.width * scale, height: size.height * scale } : undefined} className={cn(!size && 'flex min-h-0 flex-1', size && 'relative shrink-0')}>
              <webview ref={getWebviewRef(tab.id)} src={tab.initialUrl} partition={PARTITION} plugins="true"
            style={size ? { width: size.width, height: size.height, transform: `scale(${scale})`, transformOrigin: 'top left', position: 'absolute', left: 0, top: 0 } : undefined}
            className={cn('overflow-hidden rounded-xl bg-white shadow-[inset_0_0_0_1px_var(--line)]', !size && 'min-h-0 flex-1')} />
            </div>
          </div>;
        })}
        {!activeTab?.initialUrl && <div className="relative z-10 min-h-0 flex-1 overflow-auto">
          <Empty title="打开一个页面" body="Agent 起了本地服务，或者你想对照某个网页，都可以在这里看，还能点选元素发给 Atlas。" icon={<Globe size={22} />} />
          {suggestions.length > 0 && <div className="grid gap-1.5 px-2">
            <p className="m-0 mb-1 text-[12px] text-fg-3">这次对话里出现的本地地址</p>
            {suggestions.map((item) => <button key={item} type="button" onClick={() => activeTab && navigateTabRef.current(activeTab.id, item)} className="flex items-center gap-2 rounded-xl card-surface px-3 py-2 text-left text-[12.5px] text-fg hover:brightness-105">
              <ExternalLink size={13} className="shrink-0 text-brand" /><span className="truncate font-mono">{item}</span>
            </button>)}
          </div>}
        </div>}
      {/* Floats over the selected page so starting a pick never shifts what the user is about to click. */}
      {picking && !localFile && <p role="status" className="pop pointer-events-none absolute top-2 left-1/2 z-20 m-0 -translate-x-1/2 rounded-lg px-3 py-1.5 text-[12px] whitespace-nowrap text-fg">{picking === 'element' ? '点一下页面上的元素' : '按住鼠标拖出一块区域'}，按 Esc 取消</p>}
    </div>
    {pendingPick && <section aria-label="页面批注" className="shrink-0 rounded-xl border border-line bg-panel p-3 shadow-lg">
      <div className="flex items-start gap-2">
        {pendingPick.screenshot && <img src={pendingPick.screenshot} alt="已标记的页面区域" className="size-14 shrink-0 rounded-lg border border-line object-cover" />}
        <div className="min-w-0 flex-1 text-[12px] text-fg-2">
          <p className="m-0 font-medium">已标记{pendingPick.kind === 'element' ? '页面元素' : '页面区域'}</p>
          <p className="m-0 mt-1 line-clamp-2 text-fg-3">{pendingPick.kind === 'element' ? `${pendingPick.tag} · ${pendingPick.selector}` : pendingPick.text || '区域截图已准备好'}</p>
        </div>
        <button type="button" aria-label="取消页面标记" onClick={() => setPendingPick(null)} className="grid size-6 shrink-0 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><X size={13} /></button>
      </div>
      <label className="sr-only" htmlFor="browser-page-annotation">给 Atlas 的页面批注</label>
      <textarea id="browser-page-annotation" autoFocus value={annotation} onChange={(event) => setAnnotation(event.target.value)} rows={2} placeholder="补充想怎么修改或关注什么（可选）" className="mt-2 min-h-12 w-full resize-y rounded-lg bg-sunken px-2.5 py-2 text-[12px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" onKeyDown={(event) => {
        if (event.key === 'Escape') { event.preventDefault(); setPendingPick(null); }
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); finishPick(); }
      }} />
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={() => setPendingPick(null)} className="h-7 rounded-lg px-2.5 text-[12px] text-fg-3 hover:bg-hover hover:text-fg">取消</button>
        <button type="button" onClick={finishPick} className="primary-fill h-7 rounded-lg px-2.5 text-[12px]">添加到输入框</button>
      </div>
    </section>}
    {apiBaseUrl && <div className="shrink-0 border-t border-line pt-1.5">
      <button type="button" onClick={() => setRecorderOpen((value) => !value)} aria-expanded={recorderOpen}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-fg-3 hover:bg-hover hover:text-fg">
        <ScrollText size={13} />{recorderOpen ? '收起操作录制' : '操作录制（可存成技能）'}
      </button>
      {recorderOpen && <BrowserRecorderPanel apiBaseUrl={apiBaseUrl} runId={runId} events={events} userSteps={recordedUserSteps}
        onRecordingChange={(recording, id) => { if (recording) setRecordedUserSteps([]); setUserRecordingId(recording ? id : null); }}
        className="mt-2 max-h-72 overflow-auto pr-1" />}
    </div>}
  </div>;
}
