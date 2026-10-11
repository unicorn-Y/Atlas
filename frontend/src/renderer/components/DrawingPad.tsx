import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Brush, Eraser, Redo2, Trash2, Undo2, X } from 'lucide-react';
import { Dialog } from '../ui/Dialog';

type Point = { x: number; y: number };
type Stroke = { points: Point[]; color: string; width: number; erase: boolean };
const COLORS = [
  { value: '#17202a', label: '深灰' }, { value: '#d2453e', label: '红色' },
  { value: '#2867d6', label: '蓝色' }, { value: '#17835d', label: '绿色' },
  { value: '#ed9d24', label: '橙色' }, { value: '#8c58c4', label: '紫色' },
];
const WIDTHS = [3, 7, 13];
const CANVAS_WIDTH = 900;
const CANVAS_HEIGHT = 540;

function drawStroke(context: CanvasRenderingContext2D, stroke: Stroke) {
  if (!stroke.points.length) return;
  context.save();
  context.strokeStyle = stroke.erase ? '#ffffff' : stroke.color;
  context.fillStyle = stroke.erase ? '#ffffff' : stroke.color;
  context.lineWidth = stroke.erase ? 34 : stroke.width;
  context.lineCap = 'round';
  context.lineJoin = 'round';
  const first = stroke.points[0];
  context.beginPath();
  context.moveTo(first.x * CANVAS_WIDTH, first.y * CANVAS_HEIGHT);
  if (stroke.points.length === 1) {
    context.arc(first.x * CANVAS_WIDTH, first.y * CANVAS_HEIGHT, context.lineWidth / 2, 0, Math.PI * 2);
    context.fill();
  } else {
    for (const point of stroke.points.slice(1)) context.lineTo(point.x * CANVAS_WIDTH, point.y * CANVAS_HEIGHT);
    context.stroke();
  }
  context.restore();
}

/** A small, real drawing pad; the exported PNG uses the same image-attachment path as pasted images. */
export default function DrawingPad({ onAttach }: { onAttach: (dataUrl: string) => boolean }) {
  const [open, setOpen] = useState(false);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [redoStrokes, setRedoStrokes] = useState<Stroke[]>([]);
  const [color, setColor] = useState(COLORS[0].value);
  const [width, setWidth] = useState(WIDTHS[1]);
  const [erase, setErase] = useState(false);
  const [cursor, setCursor] = useState<Point>({ x: 0.5, y: 0.5 });
  const [announcement, setAnnouncement] = useState('');
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const activeStroke = useRef<Stroke | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    for (const stroke of strokes) drawStroke(context, stroke);
  }, [open, strokes]);

  const pointFromEvent = (event: ReactPointerEvent<HTMLCanvasElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    const point = { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
    setCursor(point);
    return point;
  };
  const startStroke = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const stroke: Stroke = { points: [pointFromEvent(event)], color, width, erase };
    activeStroke.current = stroke;
    const context = canvasRef.current?.getContext('2d');
    if (context) drawStroke(context, stroke);
  };
  const continueStroke = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const stroke = activeStroke.current;
    if (!stroke) return;
    event.preventDefault();
    const next = pointFromEvent(event);
    const previous = stroke.points[stroke.points.length - 1];
    stroke.points.push(next);
    const context = canvasRef.current?.getContext('2d');
    if (!context) return;
    context.save();
    context.strokeStyle = stroke.erase ? '#ffffff' : stroke.color;
    context.lineWidth = stroke.erase ? 34 : stroke.width;
    context.lineCap = 'round';
    context.beginPath();
    context.moveTo(previous.x * CANVAS_WIDTH, previous.y * CANVAS_HEIGHT);
    context.lineTo(next.x * CANVAS_WIDTH, next.y * CANVAS_HEIGHT);
    context.stroke();
    context.restore();
  };
  const finishStroke = () => {
    const stroke = activeStroke.current;
    if (!stroke) return;
    activeStroke.current = null;
    setStrokes((current) => [...current, stroke]);
    setRedoStrokes([]);
  };
  const addKeyboardMark = () => {
    const stroke: Stroke = { points: [cursor], color, width, erase };
    setStrokes((current) => [...current, stroke]);
    setRedoStrokes([]);
    setAnnouncement(`已在画布 ${Math.round(cursor.x * 100)}%、${Math.round(cursor.y * 100)}% 位置落笔`);
  };
  const attach = () => {
    const canvas = canvasRef.current;
    if (!canvas || !strokes.length) return;
    if (!onAttach(canvas.toDataURL('image/png'))) {
      setAnnouncement('白板没有附加。请移除部分附件后再试；绘图仍然保留。');
      return;
    }
    setStrokes([]);
    setRedoStrokes([]);
    setOpen(false);
  };

  return <>
    <button type="button" aria-label="打开会话白板" onClick={() => setOpen(true)}
      className="grid size-8 shrink-0 place-items-center rounded-[9px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
      <Brush size={16} />
    </button>
    <Dialog open={open} onOpenChange={setOpen} label="会话白板" className="w-[min(940px,94vw)] bg-panel p-4 shadow-xl">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="m-0 text-[16px] font-semibold text-heading">会话白板</h2>
        <span className="flex-1" />
        <button type="button" aria-label="关闭白板" onClick={() => setOpen(false)} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><X size={17} /></button>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2" aria-label="白板工具">
        {COLORS.map((item) => <button key={item.value} type="button" aria-label={`颜色：${item.label}`} aria-pressed={color === item.value && !erase} onClick={() => { setColor(item.value); setErase(false); }}
          className="grid size-8 place-items-center rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand" style={{ boxShadow: color === item.value && !erase ? `inset 0 0 0 2px ${item.value}` : undefined }}>
          <span className="size-5 rounded-full" style={{ backgroundColor: item.value }} />
        </button>)}
        <span className="mx-1 h-6 w-px bg-line" />
        {WIDTHS.map((item) => <button key={item} type="button" aria-label={`笔画粗细 ${item}`} aria-pressed={width === item} onClick={() => setWidth(item)} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
          <span className="rounded-full bg-fg" style={{ width: item + 3, height: item + 3 }} />
        </button>)}
        <button type="button" aria-label="橡皮擦" aria-pressed={erase} onClick={() => setErase((value) => !value)} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><Eraser size={16} /></button>
        <span className="flex-1" />
        <button type="button" aria-label="撤销画笔操作" disabled={!strokes.length} onClick={() => { const last = strokes.at(-1); if (last) { setStrokes(strokes.slice(0, -1)); setRedoStrokes([...redoStrokes, last]); } }} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-40"><Undo2 size={16} /></button>
        <button type="button" aria-label="重做画笔操作" disabled={!redoStrokes.length} onClick={() => { const last = redoStrokes.at(-1); if (last) { setRedoStrokes(redoStrokes.slice(0, -1)); setStrokes([...strokes, last]); } }} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-40"><Redo2 size={16} /></button>
        <button type="button" aria-label="清空白板" disabled={!strokes.length} onClick={() => { setRedoStrokes(strokes); setStrokes([]); }} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-40"><Trash2 size={16} /></button>
      </div>
      <div className="relative overflow-hidden rounded-xl border border-line bg-white">
        <canvas ref={canvasRef} width={CANVAS_WIDTH} height={CANVAS_HEIGHT} role="application" aria-label="绘图区域。鼠标或触屏拖动即可画线。聚焦后用方向键移动光标，再按空格或回车落笔。" tabIndex={0}
          onPointerDown={startStroke} onPointerMove={continueStroke} onPointerUp={finishStroke} onPointerCancel={finishStroke}
          onKeyDown={(event) => {
            const delta = event.shiftKey ? 0.05 : 0.02;
            const moves: Record<string, Point> = { ArrowLeft: { x: -delta, y: 0 }, ArrowRight: { x: delta, y: 0 }, ArrowUp: { x: 0, y: -delta }, ArrowDown: { x: 0, y: delta } };
            const move = moves[event.key];
            if (move) { event.preventDefault(); setCursor((point) => ({ x: Math.max(0, Math.min(1, point.x + move.x)), y: Math.max(0, Math.min(1, point.y + move.y)) })); }
            else if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); addKeyboardMark(); }
          }}
          className="block h-auto max-h-[60vh] w-full touch-none cursor-crosshair outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand" />
        <span aria-hidden="true" className="pointer-events-none absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border border-brand" style={{ left: `${cursor.x * 100}%`, top: `${cursor.y * 100}%` }} />
      </div>
      <p className="my-2 text-[12px] text-fg-3">鼠标或触屏拖动绘制；键盘可聚焦画布后用方向键移动、空格或回车落笔。白板会作为 PNG 图片附加到当前消息。</p>
      <span role="status" aria-live="polite" className="sr-only">{announcement}</span>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => setOpen(false)} className="rounded-lg px-3 py-2 text-[13px] text-fg-2 hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">取消</button>
        <button type="button" disabled={!strokes.length} onClick={attach} className="rounded-lg bg-brand px-3 py-2 text-[13px] font-medium text-on-primary hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-40">添加到消息</button>
      </div>
    </Dialog>
  </>;
}
