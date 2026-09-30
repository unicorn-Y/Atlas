import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, BoxSelect, Code2, Crosshair, ScrollText, ExternalLink, Globe, Monitor, RotateCw, Smartphone, Tablet, X } from 'lucide-react';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';

/** Must match BROWSER_PARTITION in the Electron main process: pages here never share the app's session. */
const PARTITION = 'persist:atlas-browser';

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

/**
 * A browser next to the conversation for checking what the Agent built.
 * Pages run in their own session with no access to Atlas; picking an element hands its details to the composer.
 */
export default function BrowserPanel({ url, onUrl, suggestions, onPick, onToast, onAsk }: {
  url: string;
  onUrl: (url: string) => void;
  /** Local servers the Agent mentioned, offered as one-click targets. */
  suggestions: string[];
  onPick: (picked: PickedElement) => void;
  onToast: (text: string) => void;
  /** Hand a request to Atlas, e.g. to summarise the open page. */
  onAsk?: (text: string) => void;
}) {
  const viewRef = useRef<WebviewElement | null>(null);
  const [address, setAddress] = useState(url);
  const [loading, setLoading] = useState(false);
  const [nav, setNav] = useState({ back: false, forward: false });
  const [picking, setPicking] = useState<'' | 'element' | 'region'>('');
  const [device, setDevice] = useState<Device>('fit');
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [stage, setStage] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const node = stageRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setStage({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(node);
    return () => observer.disconnect();
  }, [url]);
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
  const pick = async (kind: 'element' | 'region') => {
    const view = viewRef.current;
    if (!view || picking) return;
    setPicking(kind);
    try {
      const result = await view.executeJavaScript<{ selector?: string; tag?: string; text: string; html?: string; rect: Rect; viewport: number } | null>(kind === 'element' ? PICKER : REGION);
      if (!result) return;
      let screenshot: string | undefined;
      try { screenshot = await cropElement((await view.capturePage()).toDataURL(), result.rect, result.viewport); } catch { screenshot = undefined; }
      onPick({ kind, url: view.getURL(), selector: result.selector ?? '', tag: result.tag ?? '', text: result.text, html: result.html ?? '', screenshot });
    } catch {
      onToast(kind === 'element' ? '这个页面不允许点选元素' : '这个页面不允许框选');
    } finally { setPicking(''); }
  };

  if (!desktop) return <Empty title="在桌面版里使用" body="浏览器面板需要 Atlas 桌面应用，网页版里不可用。" icon={<Globe size={22} />} />;

  const size = device === 'fit' ? null : DEVICES[device];
  const scale = size && stage.width && stage.height ? Math.min(1, stage.width / size.width, stage.height / size.height) : 1;
  const button = 'grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg disabled:opacity-35 disabled:hover:bg-transparent';
  return <div className="flex h-full min-h-0 flex-col gap-2">
    <form onSubmit={go} className="flex items-center gap-1">
      <button type="button" aria-label="后退" disabled={!nav.back} onClick={() => viewRef.current?.goBack()} className={button}><ArrowLeft size={15} /></button>
      <button type="button" aria-label="前进" disabled={!nav.forward} onClick={() => viewRef.current?.goForward()} className={button}><ArrowRight size={15} /></button>
      <button type="button" aria-label={loading ? '停止加载' : '刷新'} disabled={!url} onClick={() => loading ? viewRef.current?.stop() : viewRef.current?.reload()} className={button}>{loading ? <X size={15} /> : <RotateCw size={14} />}</button>
      <input value={address} onChange={(event) => setAddress(event.target.value)} onFocus={(event) => event.target.select()} placeholder="输入网址、localhost:端口，或搜索" aria-label="地址"
        className="h-8 min-w-0 flex-1 rounded-[9px] bg-sunken px-3 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      <button type="button" aria-label="点选页面元素发给 Atlas" title="点选页面元素发给 Atlas（Esc 取消）" disabled={!url || Boolean(picking)} onClick={() => void pick('element')}
        className={cn(button, picking === 'element' && '!bg-brand-soft !text-fg')}><Crosshair size={15} /></button>
      <button type="button" aria-label="框选页面区域发给 Atlas" title="框选一块区域发给 Atlas，可以连续框选几处再发（Esc 取消）" disabled={!url || Boolean(picking)} onClick={() => void pick('region')}
        className={cn(button, picking === 'region' && '!bg-brand-soft !text-fg')}><BoxSelect size={15} /></button>
      {onAsk && <button type="button" aria-label="让 Atlas 总结这页" title="让 Atlas 读这页正文（视频读字幕）并总结要点" disabled={!url || /^(about|file|data):/i.test(url)}
        onClick={() => {
          const current = viewRef.current?.getURL() || url;
          const local = /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(current);
          onAsk(`用 web_extract 读取这个${/youtube\.com|youtu\.be|bilibili\.com/i.test(current) ? '视频的字幕' : '网页的正文'}${local ? '（是我本机的开发页面，allow_local 设为 true）' : ''}，然后用中文总结要点，最后列出值得注意的细节：
${current}`);
        }} className={button}><ScrollText size={15} /></button>}
      <button type="button" aria-label="开发者工具" disabled={!url} onClick={() => viewRef.current?.openDevTools()} className={button}><Code2 size={15} /></button>
    </form>
    {url && <div className="flex items-center gap-0.5 text-[12px]" role="group" aria-label="预览尺寸">
      {(Object.keys(DEVICES) as Device[]).map((key) => {
        const Icon = DEVICES[key].icon;
        return <button key={key} type="button" onClick={() => setDevice(key)} aria-pressed={device === key}
          className={cn('inline-flex h-6 items-center gap-1 rounded-md px-2', device === key ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}>
          <Icon size={12} />{DEVICES[key].label}</button>;
      })}
      {size && <span className="ml-auto tabular-nums text-fg-3">{size.width} × {size.height}{scale < 1 ? ` · ${Math.round(scale * 100)}%` : ''}</span>}
    </div>}
    {url
      ? <div ref={stageRef} className={cn('relative flex min-h-0 flex-1', size && 'items-start justify-center overflow-hidden')}>
        {/* Other device sizes render at full size and are scaled to fit, so the page lays out as it would there. */}
        <div style={size ? { width: size.width * scale, height: size.height * scale } : undefined} className={cn(!size && 'flex min-h-0 flex-1', size && 'relative shrink-0')}>
          <webview ref={(node) => { viewRef.current = node as WebviewElement | null; }} src={url} partition={PARTITION} plugins="true"
            style={size ? { width: size.width, height: size.height, transform: `scale(${scale})`, transformOrigin: 'top left', position: 'absolute', left: 0, top: 0 } : undefined}
            className={cn('overflow-hidden rounded-xl bg-white shadow-[inset_0_0_0_1px_var(--line)]', !size && 'min-h-0 flex-1')} />
        </div>
        {/* Floats over the page so starting a pick never shifts what the user is about to click. */}
        {picking && <p className="pop pointer-events-none absolute top-2 left-1/2 m-0 -translate-x-1/2 rounded-lg px-3 py-1.5 text-[12px] whitespace-nowrap text-fg">{picking === 'element' ? '点一下页面上的元素' : '按住鼠标拖出一块区域'}，按 Esc 取消</p>}
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
