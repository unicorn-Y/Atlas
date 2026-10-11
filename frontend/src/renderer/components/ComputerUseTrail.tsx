import { useMemo } from 'react';
import { Check, CircleAlert, Monitor } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';

function actualThumbnail(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const match = value.match(/^(data:image\/(?:jpeg|png);base64,)([A-Za-z0-9+/]+={0,2})$/i);
  if (!match || match[2].length % 4 !== 0) return undefined;
  return value;
}

/** Shows only computer actions and screenshots that arrived in Atlas's runtime event stream. */
export default function ComputerUseTrail({ events }: { events: AgentEvent[] }) {
  const steps = useMemo(() => events.filter((event) => event.type === 'computer.step'), [events]);
  const foregroundEvents = useMemo(() => events.filter((event) => event.type === 'computer.foreground_resumed' || event.type === 'computer.foreground_denied'), [events]);
  if (!steps.length && !foregroundEvents.length) return null;
  return <section className="my-3 ml-10 rounded-xl border border-line bg-surface/50 px-3 py-2.5" aria-label="电脑操作轨迹">
    <details>
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[12.5px] text-fg-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
        <Monitor size={14} className="text-brand" aria-hidden="true" />电脑操作 · {steps.length} 步
        {foregroundEvents.length > 0 && <span className="text-fg-3">· {foregroundEvents.length} 条前台状态</span>}
      </summary>
      <div className="mt-2 grid gap-2 border-t border-line pt-2">
        {foregroundEvents.map((event) => <p key={event.id} className="m-0 flex items-start gap-1.5 text-[12px] text-fg-2">
          {event.type === 'computer.foreground_resumed' ? <Check size={13} className="mt-0.5 shrink-0 text-ok" aria-hidden="true" /> : <CircleAlert size={13} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />}
          {event.type === 'computer.foreground_resumed' ? '前台操作已获允许并继续' : '前台操作未获允许'}
          {typeof event.data.reason === 'string' && event.data.reason && <span className="text-fg-3">：{event.data.reason}</span>}
        </p>)}
        {steps.length > 0 && <ol className="m-0 grid max-h-[480px] list-none gap-2 overflow-auto p-0">
          {steps.map((event, index) => {
            const tool = typeof event.data.tool === 'string' ? event.data.tool : '电脑操作';
            const ok = typeof event.data.ok === 'boolean' ? event.data.ok : null;
            const summary = typeof event.data.summary === 'string' ? event.data.summary : '';
            const thumbnail = actualThumbnail(event.data.thumbnail);
            return <li key={event.id} className="rounded-lg bg-sunken p-2.5">
              <div className="flex items-start gap-2 text-[12px]">
                <span className="w-5 shrink-0 text-right tabular-nums text-fg-3">{index + 1}.</span>
                {ok === true ? <Check size={13} className="mt-0.5 shrink-0 text-ok" aria-label="成功" /> : ok === false ? <CircleAlert size={13} className="mt-0.5 shrink-0 text-danger" aria-label="失败" /> : <Monitor size={13} className="mt-0.5 shrink-0 text-fg-3" aria-label="结果状态未知" />}
                <span className="min-w-0 flex-1 break-words text-fg-2"><code className="font-mono text-fg">{tool}</code> · {ok === true ? '成功' : ok === false ? '失败' : '状态未知'}{summary && <span> · {summary}</span>}</span>
                <time className="shrink-0 text-[10.5px] text-fg-3" dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString()}</time>
              </div>
              {thumbnail
                ? <details className="mt-1.5 ml-7">
                  <summary className="cursor-pointer text-[11.5px] text-fg-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">查看这一步的截图</summary>
                  <img src={thumbnail} alt={`电脑操作第 ${index + 1} 步的截图`} className="mt-2 max-h-64 max-w-full rounded-md border border-line object-contain" />
                </details>
                : typeof event.data.thumbnail === 'string' && <p className="m-0 mt-1 ml-7 text-[11px] text-fg-3">该事件的缩略图不完整，未显示。</p>}
            </li>;
          })}
        </ol>}
      </div>
    </details>
  </section>;
}
