import { useEffect, useId, useRef, useState, type KeyboardEvent, type MouseEvent, type SyntheticEvent } from 'react';
import { createPortal } from 'react-dom';
import { Download, Minus, Plus, RotateCcw, X } from 'lucide-react';

type ImageSize = { width: number; height: number };

function safeImageSource(value: string | undefined): value is string {
  if (!value) return false;
  if (/^data:image\/(?:png|jpe?g|gif|webp|bmp|svg\+xml)(?:;|,)/i.test(value)) return true;
  try {
    const url = new URL(value, window.location.href);
    return (url.protocol === 'http:' || url.protocol === 'https:') && !url.username && !url.password;
  } catch {
    return false;
  }
}

function imageFilename(src: string, alt: string): string {
  const safeAlt = alt.trim().replace(/[\\/:*?"<>|\u0000-\u001f]/g, '-').replace(/\s+/g, ' ').slice(0, 80);
  if (safeAlt && /\.[a-z\d]{2,8}$/i.test(safeAlt)) return safeAlt;
  try {
    const url = new URL(src, window.location.href);
    const name = decodeURIComponent(url.pathname.split('/').filter(Boolean).at(-1) ?? '');
    if (name && /\.[a-z\d]{2,8}$/i.test(name)) return name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '-');
  } catch { /* data URLs have no useful path */ }
  const mime = src.match(/^data:image\/([^;,]+)/i)?.[1]?.toLowerCase();
  const extension = mime === 'jpeg' ? 'jpg' : mime === 'svg+xml' ? 'svg' : mime || 'png';
  return `${safeAlt || 'image'}.${extension}`;
}

function downloadBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export default function ImagePreview({ src, alt = '', title }: {
  src?: string;
  alt?: string;
  title?: string;
}) {
  const usable = safeImageSource(src);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const [open, setOpen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [size, setSize] = useState<ImageSize | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [downloadError, setDownloadError] = useState('');
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      if (triggerRef.current?.isConnected) triggerRef.current.focus();
      else previous?.focus();
    };
  }, [open]);

  const close = () => setOpen(false);
  const onDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab') return;
    const controls = dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled])');
    if (!controls?.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  };

  const updateImageSize = (event: SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    setSize({ width: image.naturalWidth, height: image.naturalHeight });
    setLoadFailed(false);
  };

  const download = async () => {
    if (!src || !usable) return;
    setDownloading(true);
    setDownloadError('');
    try {
      const response = await fetch(src);
      if (!response.ok) throw new Error('download failed');
      downloadBlob(await response.blob(), imageFilename(src, alt));
    } catch {
      setDownloadError('无法直接下载此图片；可以在图片上点击右键并选择“图片另存为”。');
    } finally {
      setDownloading(false);
    }
  };

  const closeOnBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) close();
  };

  if (!usable || (loadFailed && !open)) {
    return <span role="img" aria-label={alt || '图片无法显示'} title={title} className="inline-flex rounded-md bg-sunken px-2 py-1 text-[12px] text-fg-3">
      {alt || '图片无法显示'}
    </span>;
  }

  const fit = size
    ? Math.min(1, (window.innerWidth * 0.82) / size.width, (window.innerHeight * 0.78) / size.height)
    : 1;
  const zoomedWidth = size ? Math.max(1, Math.round(size.width * fit * zoom)) : undefined;
  const zoomedHeight = size ? Math.max(1, Math.round(size.height * fit * zoom)) : undefined;
  const overlay = open && typeof document !== 'undefined' ? createPortal(
    <div className="fixed inset-0 z-[100] grid place-items-center bg-black/90 p-4" onClick={closeOnBackdrop}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onDialogKeyDown}
        className="flex h-full max-h-[95vh] w-full max-w-[96vw] flex-col text-white">
        <div className="flex min-h-11 items-center justify-between gap-3">
          <h2 id={titleId} className="min-w-0 flex-1 truncate text-sm font-medium">{alt || '图片预览'}</h2>
          <div className="flex shrink-0 items-center gap-1">
            <button type="button" aria-label="缩小图片" title="缩小" disabled={zoom <= 0.25} onClick={() => setZoom((value) => Math.max(0.25, Number((value / 1.25).toFixed(3))))}
              className="grid size-9 place-items-center rounded-lg hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-40"><Minus size={17} /></button>
            <button type="button" aria-label="重置图片缩放" title={`重置缩放（${Math.round(zoom * 100)}%）`} onClick={() => setZoom(1)}
              className="grid size-9 place-items-center rounded-lg px-2 text-[11px] hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"><RotateCcw size={15} /></button>
            <button type="button" aria-label="放大图片" title="放大" disabled={zoom >= 4} onClick={() => setZoom((value) => Math.min(4, Number((value * 1.25).toFixed(3))))}
              className="grid size-9 place-items-center rounded-lg hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-40"><Plus size={17} /></button>
            <span aria-live="polite" className="w-12 text-center text-xs text-white/75">{Math.round(zoom * 100)}%</span>
            <button type="button" aria-label="下载图片" title="下载图片" disabled={downloading} onClick={() => void download()}
              className="grid size-9 place-items-center rounded-lg hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-50"><Download size={16} /></button>
            <button ref={closeRef} type="button" aria-label="关闭图片预览" title="关闭" onClick={close}
              className="grid size-9 place-items-center rounded-lg hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"><X size={18} /></button>
          </div>
        </div>
        <div className="grid min-h-0 flex-1 place-items-center overflow-auto" onClick={closeOnBackdrop}>
          <img src={src} alt={alt || '放大预览'} onLoad={updateImageSize} onError={() => setLoadFailed(true)}
            className="block object-contain" style={size ? { width: zoomedWidth, height: zoomedHeight } : { maxWidth: '82vw', maxHeight: '78vh' }} />
        </div>
        {downloadError && <p role="status" className="mb-1 mt-2 text-center text-xs text-white/80">{downloadError}</p>}
      </div>
    </div>, document.body,
  ) : null;

  return <>
    <button ref={triggerRef} type="button" aria-label={`放大图片${alt ? `：${alt}` : ''}`} title={title || '点击放大图片'} onClick={() => { setZoom(1); setOpen(true); }}
      className="my-1 inline-block max-w-full cursor-zoom-in rounded-lg p-0 align-middle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
      <img src={src} alt={alt} onError={() => setLoadFailed(true)} className="max-h-[28rem] max-w-full rounded-lg object-contain" />
    </button>
    {overlay}
  </>;
}
