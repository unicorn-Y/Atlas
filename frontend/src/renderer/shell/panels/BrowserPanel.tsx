import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, Code2, Crosshair, ExternalLink, Globe, RotateCw, X } from 'lucide-react';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';

/** Must match BROWSER_PARTITION in the Electron main process: pages here never share the app's session. */
const PARTITION = 'persist:atlas-browser';

/** What the user picked on a page, ready to hand to the Agent. */
export interface PickedElement {
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
  executeJavaScript<T>(code: string): Promise<T>;
  capturePage(): Promise<{ toDataURL(): string }>;
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
  canvas.getContext('2d')?.drawImage(image, x, y, width, height, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/png');
}

const normalize = (value: string) => {
  const text = value.trim();
  if (!text) return '';
  if (/^(https?|file):/i.test(text)) return text;
  if (/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/i.test(text)) return `http://${text}`;
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/|$)/.test(text)) return `https://${text}`;
  return `https://www.bing.com/search?q=${encodeURIComponent(text)}`;
};

/**
 * A browser next to the conversation for checking what the Agent built.
 * Pages run in their own session with no access to Atlas; picking an element hands its details to the composer.
 */
export default function BrowserPanel({ url, onUrl, suggestions, onPick, onToast }: {
  url: string;
  onUrl: (url: string) => void;
  /** Local servers the Agent mentioned, offered as one-click targets. */
  suggestions: string[];
  onPick: (picked: PickedElement) => void;
  onToast: (text: string) => void;
}) {
  const viewRef = useRef<WebviewElement | null>(null);
  const [address, setAddress] = useState(url);
  const [loading, setLoading] = useState(false);
  const [nav, setNav] = useState({ back: false, forward: false });
  const [picking, setPicking] = useState(false);
  const desktop = typeof window !== 'undefined' && Boolean(window.atlasDesktop);

  useEffect(() => setAddress(url), [url]);
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const sync = () => { setNav({ back: view.canGoBack(), forward: view.canGoForward() }); const current = view.getURL(); setAddress(current); if (current && current !== url) onUrl(current); };
    const start = () => setLoading(true);
    const stop = () => { setLoading(false); sync(); };
    const failed = (event: Event) => {
      const detail = event as Event & { errorCode?: number; errorDescription?: string; isMainFrame?: boolean };
      if (detail.isMainFrame && detail.errorCode !== -3) onToast(`打不开这个页面：${detail.errorDescription ?? detail.errorCode}`);
    };
    view.addEventListener('did-start-loading', start);
    view.addEventListener('did-stop-loading', stop);
    view.addEventListener('did-navigate', sync);
    view.addEventListener('did-navigate-in-page', sync);
    view.addEventListener('did-fail-load', failed);
    return () => {
      view.removeEventListener('did-start-loading', start);
      view.removeEventListener('did-stop-loading', stop);
      view.removeEventListener('did-navigate', sync);
      view.removeEventListener('did-navigate-in-page', sync);
      view.removeEventListener('did-fail-load', failed);
    };
  }, [url, onUrl, onToast]);

  const go = (event?: FormEvent) => {
    event?.preventDefault();
    const next = normalize(address);
    if (!next) return;
    if (viewRef.current && url) void viewRef.current.loadURL(next).catch(() => undefined);
    onUrl(next);
  };
  const pick = async () => {
    const view = viewRef.current;
    if (!view || picking) return;
    setPicking(true);
    try {
      const result = await view.executeJavaScript<{ selector: string; tag: string; text: string; html: string; rect: Rect; viewport: number } | null>(PICKER);
      if (!result) return;
      let screenshot: string | undefined;
      try { screenshot = await cropElement((await view.capturePage()).toDataURL(), result.rect, result.viewport); } catch { screenshot = undefined; }
      onPick({ url: view.getURL(), selector: result.selector, tag: result.tag, text: result.text, html: result.html, screenshot });
    } catch {
      onToast('这个页面不允许点选元素');
    } finally { setPicking(false); }
  };

  if (!desktop) return <Empty title="在桌面版里使用" body="浏览器面板需要 Atlas 桌面应用，网页版里不可用。" icon={<Globe size={22} />} />;

  const button = 'grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg disabled:opacity-35 disabled:hover:bg-transparent';
  return <div className="flex h-full min-h-0 flex-col gap-2">
    <form onSubmit={go} className="flex items-center gap-1">
      <button type="button" aria-label="后退" disabled={!nav.back} onClick={() => viewRef.current?.goBack()} className={button}><ArrowLeft size={15} /></button>
      <button type="button" aria-label="前进" disabled={!nav.forward} onClick={() => viewRef.current?.goForward()} className={button}><ArrowRight size={15} /></button>
      <button type="button" aria-label={loading ? '停止加载' : '刷新'} disabled={!url} onClick={() => loading ? viewRef.current?.stop() : viewRef.current?.reload()} className={button}>{loading ? <X size={15} /> : <RotateCw size={14} />}</button>
      <input value={address} onChange={(event) => setAddress(event.target.value)} onFocus={(event) => event.target.select()} placeholder="输入网址、localhost:端口，或搜索" aria-label="地址"
        className="h-8 min-w-0 flex-1 rounded-[9px] bg-sunken px-3 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      <button type="button" aria-label="点选页面元素发给 Atlas" title="点选页面元素发给 Atlas（Esc 取消）" disabled={!url || picking} onClick={() => void pick()}
        className={cn(button, picking && '!bg-brand-soft !text-fg')}><Crosshair size={15} /></button>
      <button type="button" aria-label="开发者工具" disabled={!url} onClick={() => viewRef.current?.openDevTools()} className={button}><Code2 size={15} /></button>
    </form>
    {url
      ? <div className="relative flex min-h-0 flex-1">
        <webview ref={(node) => { viewRef.current = node as WebviewElement | null; }} src={url} partition={PARTITION} plugins="true"
          className="min-h-0 flex-1 overflow-hidden rounded-xl bg-white shadow-[inset_0_0_0_1px_var(--line)]" />
        {/* Floats over the page so starting a pick never shifts what the user is about to click. */}
        {picking && <p className="pop pointer-events-none absolute top-2 left-1/2 m-0 -translate-x-1/2 rounded-lg px-3 py-1.5 text-[12px] whitespace-nowrap text-fg">点一下页面上的元素，按 Esc 取消</p>}
      </div>
      : <div className="min-h-0 flex-1 overflow-auto">
        <Empty title="打开一个页面" body="Agent 起了本地服务，或者你想对照某个网页，都可以在这里看，还能点选元素发给 Atlas。" icon={<Globe size={22} />} />
        {suggestions.length > 0 && <div className="grid gap-1.5 px-2">
          <p className="m-0 mb-1 text-[12px] text-fg-3">这次对话里出现的本地地址</p>
          {suggestions.map((item) => <button key={item} onClick={() => onUrl(item)} className="flex items-center gap-2 rounded-xl card-surface px-3 py-2 text-left text-[12.5px] text-fg hover:brightness-105">
            <ExternalLink size={13} className="shrink-0 text-brand" /><span className="truncate font-mono">{item}</span>
          </button>)}
        </div>}
      </div>}
  </div>;
}
